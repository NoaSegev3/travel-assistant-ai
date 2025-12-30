# Role: Small typed contract for routing. Decision is the output of DecisionLogic and drives the FlowController:
# (ask clarification / call tool / generate response / out-of-scope). Validator enforces "tool_name only for tools".

from __future__ import annotations

from enum import Enum
from typing import List, Optional
from typing import Any, Dict

from pydantic import BaseModel, Field, model_validator


class Action(str, Enum):
    ASK_CLARIFICATION = "ask_clarification"
    GENERATE_RESPONSE = "generate_response"
    CALL_TOOL = "call_tool"
    OUT_OF_SCOPE_RESPONSE = "out_of_scope_response"


class Decision(BaseModel):
    action: Action
    missing_info: List[str] = Field(default_factory=list)
    tool_name: Optional[str] = None
    notes: Optional[str] = None
    tool_payload: Optional[Dict[str, Any]] = None

    @model_validator(mode="after")
    def _check_tool_name(self):
        # CALL_TOOL requires tool_name
        if self.action == Action.CALL_TOOL and not self.tool_name:
            raise ValueError("tool_name is required when action=CALL_TOOL")

        # Non-tool actions must not carry tool_name/tool_payload
        if self.action != Action.CALL_TOOL:
            if self.tool_name is not None:
                raise ValueError("tool_name must be None unless action=CALL_TOOL")
            if self.tool_payload is not None:
                raise ValueError("tool_payload must be None unless action=CALL_TOOL")

        return self

