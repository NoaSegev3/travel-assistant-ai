# Role: Per-session state container. Holds the evolving TripProfile and conversation history,
# plus small "flow memory" fields like last_intent and pending_missing_info.

from datetime import datetime, timezone
from typing import List, Optional

from pydantic import BaseModel, Field

from backend.models.intent import Intent
from backend.models.message import Message
from backend.models.trip_profile import TripProfile


class State(BaseModel):
    session_id: str
    trip_profile: TripProfile = Field(default_factory=TripProfile)
    conversation_history: List[Message] = Field(default_factory=list)

    # Key line: last_intent is how we keep a "current goal" for constraints updates (follow-ups).
    last_intent: Optional[Intent] = None

    # Key line: primary_intent is the main conversational goal to return to after interrupts
    primary_intent: Optional[Intent] = None

    turn_count: int = 0

    # Key line: single-slot clarification loop ("what are we waiting for?").
    pending_missing_info: List[str] = Field(default_factory=list)

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

