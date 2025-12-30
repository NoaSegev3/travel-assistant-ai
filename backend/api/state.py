# Role: Read-only transparency endpoint for the UI.
# Does NOT change any flow logic. Only exposes current state snapshot by session_id.

from fastapi import APIRouter
from pydantic import BaseModel
from backend.api.deps import flow_controller

router = APIRouter(tags=["state"])

class StateSnapshot(BaseModel):
    session_id: str
    trip_profile: dict
    pending_missing_info: list[str]
    last_intent: str | None
    turn_count: int

@router.get("/state/{session_id}", response_model=StateSnapshot)
def get_state(session_id: str) -> StateSnapshot:
    state = flow_controller.state_manager.get_or_create(session_id)
    return StateSnapshot(
        session_id=session_id,
        trip_profile=state.trip_profile.model_dump(),
        pending_missing_info=state.pending_missing_info,
        last_intent=state.last_intent.value if state.last_intent else None,
        turn_count=state.turn_count,
    )