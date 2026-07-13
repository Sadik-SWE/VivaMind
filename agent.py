"""
VivaMind — Step M3: multi-agent viva panel (replaces the M2 single-examiner agent.py).

Flow:
    IntakeAgent  ->  PanelExaminer(HR)  ->  (Technical)  ->  (PM)  ->  ClosingAgent

- Handoff: an examiner calls the `section_complete` tool, which RETURNS the next
  Agent. LiveKit swaps the active agent in the same live session — the candidate
  never notices a "restart".
- Shared state: the candidate's name, department and per-section notes live in a
  typed `CandidateData` object on the session, so every examiner can read it and
  M4 scoring has structured data to work with.
- Scaling: the number of examiners is decided by ACTIVE_PANEL below. Change the
  slice to go from a 3-agent demo to the full 8-agent panel — no other edits.

Run:
    python agent.py dev
(then connect from the Agents Playground — see SETUP.md)
"""

import logging
from dataclasses import dataclass, field
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
logger = logging.getLogger("vivamind")

# ---------------------------------------------------------------------------
# How many examiners run. First 3 = demo-friendly (HR, Technical, PM).
# For the full panel, change to:  ACTIVE_PANEL = PANEL
# ---------------------------------------------------------------------------
ACTIVE_PANEL = PANEL[:3]


@dataclass
class CandidateData:
    """Shared record that travels with the session across every handoff."""
    name: Optional[str] = None
    department: Optional[str] = None
    stage_index: int = 0
    notes: dict = field(default_factory=dict)  # stage_key -> examiner's note (M4 scoring)


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
    """One examiner. Asks its section, then hands off to the next (or closes)."""

    def __init__(self, stage_index: int) -> None:
        self.stage_index = stage_index
        self.stage = ACTIVE_PANEL[stage_index]
        super().__init__(instructions=build_examiner_instructions(self.stage))
        # To make it feel like a real panel, give each examiner a distinct voice:
        #   super().__init__(instructions=..., tts="cartesia/sonic-2:<VOICE_ID>")
        # (fill valid Cartesia voice IDs from your LiveKit/Cartesia dashboard.)

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
        self, context: RunContext[CandidateData], brief_note: str
    ) -> tuple[Agent, str]:
        """Call this once you have asked your two questions for this section.

        Args:
            brief_note: A 1-2 sentence neutral observation about the candidate's
                answers, for the panel's records.
        """
        ud = context.userdata
        ud.notes[self.stage["key"]] = brief_note

        next_index = self.stage_index + 1
        if next_index < len(ACTIVE_PANEL):
            ud.stage_index = next_index
            next_name = ACTIVE_PANEL[next_index]["name"]
            return PanelExaminer(next_index), f"Now handing over to the {next_name}."
        return ClosingAgent(), "That completes the panel."


class ClosingAgent(Agent):
    """Thanks the candidate and ends without revealing any result."""

    def __init__(self) -> None:
        super().__init__(instructions=CLOSING_INSTRUCTIONS)

    async def on_enter(self) -> None:
        ud = self.session.userdata
        name = ud.name or "the candidate"
        logger.info("Viva complete for %s. Notes: %s", name, ud.notes)
        await self.session.generate_reply(
            instructions=f"Thank {name} for attending, say the panel will share "
                         f"results later, and end warmly."
        )


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
