# Role: Streamlit chat UI.
# - Backend is authoritative (chat + snapshot).
# - Sidebar shows ONLY a human-readable Trip Summary.

from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

import requests
import streamlit as st

BACKEND_URL = "http://127.0.0.1:8000"


# ----------------------------
# Session helpers
# ----------------------------
def ensure_session() -> None:
    if "session_id" not in st.session_state:
        st.session_state["session_id"] = str(uuid.uuid4())
    if "messages" not in st.session_state:
        st.session_state["messages"] = []
    if "busy" not in st.session_state:
        st.session_state["busy"] = False
    if "snapshot" not in st.session_state:
        st.session_state["snapshot"] = None


# ----------------------------
# Backend calls
# ----------------------------
def send_to_backend(session_id: str, user_message: str) -> str:
    resp = requests.post(
        f"{BACKEND_URL}/chat",
        json={"session_id": session_id, "user_message": user_message},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["assistant_message"]


def fetch_snapshot(session_id: str) -> Optional[Dict[str, Any]]:
    try:
        r = requests.get(f"{BACKEND_URL}/state/{session_id}", timeout=10)
        if r.status_code != 200:
            return None
        return r.json()
    except requests.RequestException:
        return None


# ----------------------------
# UI polish
# ----------------------------
def inject_css() -> None:
    st.markdown(
        """
<style>
/* Wide layout so chat input feels long */
.block-container { max-width: 1200px; padding-top: 2rem; padding-bottom: 2rem; }

/* Sidebar spacing */
section[data-testid="stSidebar"] .block-container { padding-top: 1.25rem; }

/* Buttons */
.stButton>button {
  border-radius: 12px !important;
  padding: 0.60rem 0.90rem !important;
  font-weight: 650 !important;
}

/* Hide ellipse decorations */
section[data-testid="stSidebar"] .element-container::before,
section[data-testid="stSidebar"] .element-container::after,
section[data-testid="stSidebar"] [data-testid="stDecoration"],
section[data-testid="stSidebar"] svg[data-testid*="icon"],
.ta-card::before,
.ta-card::after {
  display: none !important;
}

/* Trip summary card */
.ta-card {
  border: 1px solid rgba(49, 51, 63, 0.14);
  border-radius: 16px;
  padding: 14px 14px;
  background: rgba(255, 255, 255, 0.02);
}

/* Card title */
.ta-title {
  font-size: 0.95rem;
  font-weight: 750;
  opacity: 0.9;
  margin-bottom: 10px;
}

/* Rows (vertical list) */
.ta-row {
  display: flex;
  align-items: baseline;
  gap: 10px;
  padding: 10px 10px;
  border: 1px solid rgba(49, 51, 63, 0.10);
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.015);
  margin-bottom: 10px;
}

.ta-icon {
  width: 22px;
  flex: 0 0 22px;
  opacity: 0.95;
}

.ta-k {
  font-size: 0.85rem;
  opacity: 0.72;
  margin-bottom: 2px;
}

.ta-v {
  font-size: 1.02rem;
  font-weight: 750;
  line-height: 1.15;
}

.ta-col {
  display: flex;
  flex-direction: column;
}

/* Chat input height */
div[data-testid="stChatInput"] textarea { min-height: 44px; }
</style>
""",
        unsafe_allow_html=True,
    )

# ----------------------------
# Formatting helpers
# ----------------------------
def _title_case_city(s: Optional[str]) -> Optional[str]:
    if not s or not isinstance(s, str):
        return None
    s = s.strip()
    if not s:
        return None
    return " ".join(w.capitalize() for w in s.split())


def _fmt_date_range(trip: Dict[str, Any]) -> str:
    start = trip.get("start_date")
    end = trip.get("end_date")
    duration = trip.get("duration_days")

    if start and end:
        return f"{start} → {end}"
    if start and not end:
        return f"From {start}"
    if duration:
        try:
            d = int(duration)
            return f"{d} day{'s' if d != 1 else ''}"
        except Exception:
            return str(duration)

    return "Not set"


def _fmt_value(v: Any) -> str:
    if v is None:
        return "—"
    if isinstance(v, str):
        s = v.strip()
        return s if s else "—"
    return str(v)


def _row(icon: str, label: str, value: str) -> str:
    return f"""
<div class="ta-row">
  <div class="ta-icon">{icon}</div>
  <div class="ta-col">
    <div class="ta-k">{label}</div>
    <div class="ta-v">{value}</div>
  </div>
</div>
"""


# ----------------------------
# Sidebar: Human Trip Summary ONLY
# ----------------------------
def render_trip_summary(snapshot: Dict[str, Any]) -> None:
    trip = (snapshot or {}).get("trip_profile") or {}

    destination = _title_case_city(trip.get("destination")) or "Not set"
    dates = _fmt_date_range(trip)

    travelers = _fmt_value(trip.get("travelers"))
    budget = _fmt_value(trip.get("budget"))
    pace = _fmt_value(trip.get("pace"))

    # Render as one complete HTML block with no gaps
    full_html = f"""
<div class="ta-card">
<div class="ta-title">Trip summary</div>
{_row("📍", "Destination", destination)}
{_row("🗓️", "Dates / Duration", dates)}
{_row("👥", "Travelers", travelers)}
{_row("💸", "Budget", budget)}
{_row("⚡", "Pace", pace)}
</div>
"""
    
    st.sidebar.markdown(full_html, unsafe_allow_html=True)


def render_sidebar() -> None:
    st.sidebar.title("Your trip")

    col1, col2 = st.sidebar.columns(2)
    with col1:
        if st.button("📍 New chat", use_container_width=True, disabled=st.session_state["busy"]):
            st.session_state["session_id"] = str(uuid.uuid4())
            st.session_state["messages"] = []
            st.session_state["snapshot"] = None
            st.rerun()

    with col2:
        if st.button("↻ Update trip", use_container_width=True, disabled=st.session_state["busy"]):
            st.session_state["snapshot"] = fetch_snapshot(st.session_state["session_id"])
            st.rerun()

    st.sidebar.divider()

    snap = st.session_state.get("snapshot")
    if not snap:
        st.sidebar.info("Start chatting to build your trip summary.")
        return

    render_trip_summary(snap)


# ----------------------------
# Chat
# ----------------------------
def render_chat() -> None:
    for msg in st.session_state["messages"]:
        with st.chat_message(msg["role"]):
            st.write(msg["content"])


# ----------------------------
# Main
# ----------------------------
def main() -> None:
    st.set_page_config(page_title="Travel Assistant", page_icon="📍", layout="wide")
    inject_css()

    st.title("📍 Travel Assistant")
    st.caption("Ask about itineraries, attractions, packing, weather, or currency conversion.")

    ensure_session()
    render_sidebar()
    render_chat()

    user_input = st.chat_input("Ask me about your trip…", disabled=st.session_state["busy"])
    if not user_input:
        return

    # Echo user message immediately
    st.session_state["messages"].append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.write(user_input)

    st.session_state["busy"] = True
    try:
        with st.spinner("Thinking..."):
            assistant_text = send_to_backend(st.session_state["session_id"], user_input)

        st.session_state["messages"].append({"role": "assistant", "content": assistant_text})
        with st.chat_message("assistant"):
            st.write(assistant_text)

        # Refresh snapshot after each turn
        st.session_state["snapshot"] = fetch_snapshot(st.session_state["session_id"])

    except requests.RequestException:
        msg = "I couldn’t reach the backend. Make sure the API is running on http://127.0.0.1:8000."
        st.session_state["messages"].append({"role": "assistant", "content": msg})
        with st.chat_message("assistant"):
            st.error(msg)
    finally:
        st.session_state["busy"] = False


if __name__ == "__main__":
    main()