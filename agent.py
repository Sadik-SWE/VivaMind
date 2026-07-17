"""
VivaMind — Step M4: multi-agent viva panel + rubric scoring + saved report.

Flow:
    IntakeAgent -> PanelExaminer(HR) -> (Technical) -> (PM) -> ClosingAgent

New in M4:
- Each examiner scores its rubric dimension 0-10 with a justification (explainable).
- At the end, a full report is compiled, printed to the terminal, and SAVED as a
  JSON file in ./reports. The candidate is never told the score (human-in-the-loop:
  the report goes to the faculty board, which makes the final decision).

Run:
    python agent.py dev
(then connect from the Agent Console — see SETUP.md)
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

from livekit import agents
from livekit.agents import Agent, AgentSession, RunContext, function_tool
from livekit.plugins import silero

from prompts import (
    PANEL,
    INTAKE_INSTRUCTIONS,
    CLOSING_INSTRUCTIONS,
    build_examiner_instructions,
)

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("vivamind")

# ---------------------------------------------------------------------------
# How many examiners run. First 3 = demo-friendly (HR, Technical, PM).
# For the full panel, change to:  ACTIVE_PANEL = PANEL
# ---------------------------------------------------------------------------
ACTIVE_PANEL = PANEL[:3]

PASS_THRESHOLD = 6.0  # avg >= this -> recommended (a recommendation, not a decision)


@dataclass
class CandidateData:
    """Shared record that travels with the session across every handoff."""
    name: Optional[str] = None
    department: Optional[str] = None
    stage_index: int = 0
    # dimension -> {"score": int, "justification": str}
    scores: dict = field(default_factory=dict)


# --------------------------- report helpers --------------------------------
def build_report(ud: CandidateData) -> dict:
    values = [v["score"] for v in ud.scores.values()] or [0]
    overall = round(sum(values) / len(values), 1)
    return {
        "candidate": ud.name,
        "department": ud.department,
        "scores": ud.scores,
        "overall": overall,
        "recommendation": (
            "Recommended for panel review"
            if overall >= PASS_THRESHOLD
            else "Needs further panel discussion"
        ),
        "note": "AI-generated recommendation only. The final admission decision "
                "rests with the human faculty board.",
        "timestamp": datetime.now().isoformat(timespec="seconds"),
    }


def save_report(report: dict) -> str:
    Path("reports").mkdir(exist_ok=True)
    safe = (report["candidate"] or "candidate").replace(" ", "_")
    path = f"reports/{safe}_{datetime.now():%Y%m%d_%H%M%S}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    return path


def print_report(report: dict, path: str) -> None:
    line = "=" * 52
    print("\n" + line)
    print("   VivaMind — Score Report")
    print(line)
    print(f" Candidate : {report['candidate']} ({report['department']})")
    print("-" * 52)
    for dim, v in report["scores"].items():
        print(f" {dim}: {v['score']}/10 — {v['justification']}")
    print("-" * 52)
    print(f" Overall   : {report['overall']}/10")
    print(f" Suggestion: {report['recommendation']}")
    print(" (AI recommendation — human faculty board decides.)")
    print(f" Saved     : {path}")
    print(line + "\n")


# ------------------------------- agents ------------------------------------
class IntakeAgent(Agent):
    """Collects the candidate's name + department, then starts the panel."""

    def __init__(self) -> None:
        super().__init__(instructions=INTAKE_INSTRUCTIONS)

    async def on_enter(self) -> None:
        await self.session.generate_reply(
            instructions="Greet the candidate, introduce VivaMind, and ask their "
                         "name and the department they are applying to."
        )

    @function_tool
    async def start_viva(
        self, context: RunContext[CandidateData], name: str, department: str
    ) -> tuple[Agent, str]:
        """Record the candidate's details and begin the viva panel.

        Args:
            name: The candidate's full name.
            department: The department / program they are applying to.
        """
        ud = context.userdata
        ud.name = name
        ud.department = department
        ud.stage_index = 0
        logger.info("Candidate: %s applying to %s", name, department)
        return PanelExaminer(0), f"Thank you, {name}. Let's begin your viva."


class PanelExaminer(Agent):
    """One examiner. Asks its section, scores it, then hands off (or closes)."""

    def __init__(self, stage_index: int) -> None:
        self.stage_index = stage_index
        self.stage = ACTIVE_PANEL[stage_index]
        super().__init__(instructions=build_examiner_instructions(self.stage))
        # For a real panel feel, give each examiner a distinct voice:
        #   super().__init__(instructions=..., tts="cartesia/sonic-2:<VOICE_ID>")

    async def on_enter(self) -> None:
        ud = self.session.userdata
        dept = ud.department or "their intended department"
        name = ud.name or "the candidate"
        await self.session.generate_reply(
            instructions=(
                f"Introduce yourself in one short line as the {self.stage['name']}. "
                f"The candidate is {name}, applying to {dept}. "
                f"Then ask your first question about {self.stage['focus']}."
            )
        )

    @function_tool
    async def section_complete(
        self, context: RunContext[CandidateData], score: int, justification: str
    ) -> tuple[Agent, str]:
        """Call this once you have asked your questions and can score this section.

        Args:
            score: Integer 0-10 rating the candidate on this section's dimension.
            justification: One or two neutral sentences explaining the score.
        """
        ud = context.userdata
        ud.scores[self.stage["dimension"]] = {
            "score": max(0, min(10, int(score))),
            "justification": justification,
        }
        logger.info("Scored %s: %s/10", self.stage["dimension"], score)

        next_index = self.stage_index + 1
        if next_index < len(ACTIVE_PANEL):
            ud.stage_index = next_index
            next_name = ACTIVE_PANEL[next_index]["name"]
            return PanelExaminer(next_index), f"Now handing over to the {next_name}."
        return ClosingAgent(), "That completes the panel."


class ClosingAgent(Agent):
    """Thanks the candidate, then compiles + saves the report (never read aloud)."""

    def __init__(self) -> None:
        super().__init__(instructions=CLOSING_INSTRUCTIONS)

    async def on_enter(self) -> None:
        ud = self.session.userdata
        name = ud.name or "the candidate"
        await self.session.generate_reply(
            instructions=f"Thank {name} for attending, say the panel will share "
                         f"results later, and end warmly. Do NOT mention any score."
        )
        # Compile + save the report server-side (goes to faculty, not the candidate).
        report = build_report(ud)
        path = save_report(report)
        print_report(report, path)


async def entrypoint(ctx: agents.JobContext) -> None:
    await ctx.connect()

    session = AgentSession[CandidateData](
        userdata=CandidateData(),
        stt="deepgram/nova-3",       # multilingual (Bangla + English)
        llm="openai/gpt-4.1-mini",   # cheap default; escalate per-agent if needed
        tts="cartesia/sonic-2",
        vad=silero.VAD.load(),
    )

    await session.start(agent=IntakeAgent(), room=ctx.room)


if __name__ == "__main__":
    agents.cli.run_app(agents.WorkerOptions(entrypoint_fnc=entrypoint))
