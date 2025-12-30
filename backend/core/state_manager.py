# Role: In-memory session store. Owns lifecycle of State objects:
# create/get by session_id, append messages, enforce bounded history, and cleanup expired sessions.

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Dict

from backend.models.message import Message
from backend.models.state import State


class StateManager:
    def __init__(self, max_history_messages: int = 12, session_ttl_minutes: int = 60) -> None:
        self._states: Dict[str, State] = {}
        self._max_history_messages = max_history_messages
        self._ttl = timedelta(minutes=session_ttl_minutes)

    def get_or_create(self, session_id: str) -> State:
        # Reuse existing state or initialize a fresh one.
        state = self._states.get(session_id)
        if state is None:
            state = State(session_id=session_id)
            self._states[session_id] = state
        return state

    def add_message(self, session_id: str, role: str, content: str) -> State:
        # 1) Append message
        # 2) Update last-seen timestamp
        # 3) Trim to last N messages (keeps prompts small + bounded memory)
        state = self.get_or_create(session_id)
        state.conversation_history.append(Message(role=role, content=content))
        state.updated_at = datetime.now(timezone.utc)

        if len(state.conversation_history) > self._max_history_messages:
            state.conversation_history = state.conversation_history[-self._max_history_messages :]

        return state

    def increment_turn(self, state: State) -> None:
        # Key line: turn_count is useful for debugging and future policies (rate-limits, etc.).
        state.turn_count += 1
        state.updated_at = datetime.now(timezone.utc)

    def cleanup_expired(self) -> int:
        # Role: drop inactive sessions to avoid unbounded growth (best for long-running servers).
        now = datetime.now(timezone.utc)
        to_delete = [sid for sid, st in self._states.items() if (now - st.updated_at) > self._ttl]
        for sid in to_delete:
            del self._states[sid]
        return len(to_delete)
