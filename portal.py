"""
VivaMind Portal — the end-to-end wrapper flow.

Landing -> Login -> Document Upload -> OCR + Verification -> Identity note ->
Join Viva (opens the LiveKit playground) -> Faculty Dashboard (reads the saved
viva reports + audit chain).

The live viva itself runs in the LiveKit playground/agent (already working).
This portal ties the whole journey together for a full demo.

Run:
    pip install streamlit pillow pandas
    streamlit run portal.py
"""

import json
from pathlib import Path

import pandas as pd
import streamlit as st

REPORTS_DIR = "reports"
TEAL = "#0E9C8A"
PLAYGROUND_URL = "http://localhost:3000"   # your LiveKit playground

# Mock education-board database (stand-in for a real board/university API).
# In production this becomes a real Education-Board / University-DB lookup.
BOARD_DB = {
    "1234567890": {"name": "Shahariar Sadik", "gpa": 5.00, "exam": "HSC"},
    "1111111111": {"name": "Rahim Uddin", "gpa": 4.50, "exam": "HSC"},
    "2222222222": {"name": "Karim Ahmed", "gpa": 4.83, "exam": "HSC"},
}


# --------------------------- verification logic ----------------------------
def verify_candidate(name: str, roll: str) -> dict:
    """Cross-check the candidate's name + roll against the board DB."""
    roll = (roll or "").strip()
    name = (name or "").strip()
    record = BOARD_DB.get(roll)
    if record is None:
        return {"status": "NOT FOUND", "ok": False,
                "detail": "Roll not found in board records — possible fake certificate."}
    if name.lower() != record["name"].lower():
        return {"status": "MISMATCH", "ok": False,
                "detail": f"Name mismatch — certificate says '{record['name']}', "
                          f"candidate entered '{name}'. Flagged for review."}
    return {"status": "VERIFIED", "ok": True,
            "detail": f"Matched board record: {record['name']}, "
                      f"{record['exam']} GPA {record['gpa']}."}


def try_ocr(image_bytes: bytes) -> str:
    """Best-effort OCR. Uses pytesseract if installed, else returns ''."""
    try:
        import io
        import pytesseract
        from PIL import Image
        img = Image.open(io.BytesIO(image_bytes))
        return pytesseract.image_to_string(img)
    except Exception:
        return ""  # graceful fallback -> manual entry


# --------------------------- faculty dashboard -----------------------------
def load_reports(reports_dir: str = REPORTS_DIR) -> pd.DataFrame:
    rows = []
    p = Path(reports_dir)
    if p.exists():
        for f in sorted(p.glob("*.json")):
            if f.name == "audit_chain.json":
                continue
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            rows.append({
                "Report ID": d.get("report_id", "-"),
                "Candidate": d.get("candidate", "-"),
                "Department": d.get("department", "-"),
                "Overall": d.get("overall", "-"),
                "Recommendation": d.get("recommendation", "-"),
            })
    return pd.DataFrame(rows)


def audit_status(reports_dir: str = REPORTS_DIR) -> str:
    try:
        import audit
        r = audit.verify(reports_dir)
        return "✅ INTACT" if r["ok"] else "❌ " + "; ".join(r["problems"])
    except Exception:
        return "audit.py not found (run the portal from your agent folder)"


# ------------------------------- UI ----------------------------------------
st.set_page_config(page_title="VivaMind Portal", page_icon="🎓", layout="centered")

if "step" not in st.session_state:
    st.session_state.step = 0
if "candidate" not in st.session_state:
    st.session_state.candidate = {}

# Sidebar: jump to Faculty Dashboard anytime
mode = st.sidebar.radio("View", ["Candidate journey", "Faculty dashboard"])

STEPS = ["Landing", "Login", "Document upload", "Verification", "Join viva"]


def header():
    st.markdown(f"<h2 style='color:{TEAL};margin-bottom:0'>🎓 VivaMind</h2>"
                "<p style='color:#64748B;margin-top:2px'>AI-Powered Admission Viva Panel</p>",
                unsafe_allow_html=True)


if mode == "Faculty dashboard":
    header()
    st.subheader("Faculty Dashboard")
    st.caption("Every completed viva, with its explainable score and tamper-proof audit status.")
    df = load_reports()
    if df.empty:
        st.info("No viva reports yet. Complete a viva (in the playground) to see results here.")
    else:
        st.dataframe(df, use_container_width=True, hide_index=True)
        st.metric("Audit chain", audit_status())
    st.caption("Cluster intelligence (scheduling/GPU/cost): run `streamlit run cluster_dashboard.py`.  "
               "LLM token/cost analytics: Langfuse dashboard.")
    st.stop()

# ---- Candidate journey (wizard) ----
header()
step = st.session_state.step
st.progress(step / (len(STEPS) - 1), text=f"Step {step + 1} of {len(STEPS)} — {STEPS[step]}")

if step == 0:  # Landing
    st.write("Welcome to **VivaMind** — a fair, explainable, multi-agent AI admission viva. "
             "Verify your documents, then attend a live voice viva with an AI examiner panel.")
    if st.button("Get started  →", type="primary"):
        st.session_state.step = 1
        st.rerun()

elif step == 1:  # Login
    st.subheader("Candidate login")
    name = st.text_input("Full name", st.session_state.candidate.get("name", ""))
    dept = st.text_input("Department applying to", st.session_state.candidate.get("dept", ""))
    if st.button("Continue  →", type="primary"):
        if name and dept:
            st.session_state.candidate.update({"name": name, "dept": dept})
            st.session_state.step = 2
            st.rerun()
        else:
            st.warning("Please enter your name and department.")

elif step == 2:  # Document upload
    st.subheader("Upload your certificate (SSC/HSC)")
    up = st.file_uploader("Certificate image", type=["png", "jpg", "jpeg"])
    if up is not None:
        st.image(up, caption="Uploaded certificate", use_container_width=True)
        st.session_state.candidate["doc"] = up.getvalue()
    if st.button("Continue  →", type="primary"):
        if st.session_state.candidate.get("doc"):
            st.session_state.step = 3
            st.rerun()
        else:
            st.warning("Please upload your certificate image.")

elif step == 3:  # OCR + Verification
    st.subheader("Document verification")
    ocr_text = try_ocr(st.session_state.candidate.get("doc", b""))
    if ocr_text.strip():
        st.text_area("OCR extracted text", ocr_text, height=120)
    else:
        st.info("Automatic OCR not available here — enter the roll from your certificate "
                "(this stands in for OCR; install Tesseract for automatic extraction).")
    roll = st.text_input("Board roll number", st.session_state.candidate.get("roll", ""))
    st.caption("Try demo roll **1234567890** with name **Shahariar Sadik** for a VERIFIED result.")
    if st.button("Verify  →", type="primary"):
        result = verify_candidate(st.session_state.candidate.get("name", ""), roll)
        st.session_state.candidate["roll"] = roll
        st.session_state.candidate["verify"] = result
        st.rerun()
    result = st.session_state.candidate.get("verify")
    if result:
        if result["ok"]:
            st.success(f"**{result['status']}** — {result['detail']}")
            if st.button("Proceed to viva  →", type="primary"):
                st.session_state.step = 4
                st.rerun()
        else:
            st.error(f"**{result['status']}** — {result['detail']}")

elif step == 4:  # Identity + Join viva
    c = st.session_state.candidate
    st.subheader("Ready for your viva")
    st.write(f"**{c.get('name')}** — {c.get('dept')}  ·  document **verified** ✅")
    st.info("During the viva, on-device **proctoring** checks that only you are present "
            "(face + multi-person detection).")
    st.link_button("🎙️  Join the live viva", PLAYGROUND_URL, type="primary")
    st.caption("Opens the VivaMind live room. Your AI examiner panel (HR → Technical → PM) "
               "will conduct the viva; your score report is saved for the faculty dashboard.")
    if st.button("← Start over"):
        st.session_state.step = 0
        st.session_state.candidate = {}
        st.rerun()