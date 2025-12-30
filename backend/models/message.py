# Role: Single chat message schema for conversation_history. Stored in State and passed into prompts
# (role + content + timestamp). Pydantic makes it easy to serialize/debug.

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

Role = Literal["user", "assistant", "system"]


class Message(BaseModel):
    role: Role
    content: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
