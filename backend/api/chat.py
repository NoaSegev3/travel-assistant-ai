# Role: Thin HTTP adapter for the chat endpoint. Validates request/response shapes and delegates the entire
# conversation turn to FlowController (business logic lives in core, not in the API layer).

from fastapi import APIRouter
from pydantic import BaseModel
from backend.api.deps import flow_controller

router = APIRouter(tags=["chat"])

class ChatRequest(BaseModel):
    session_id: str
    user_message: str

class ChatResponse(BaseModel):
    session_id: str
    assistant_message: str

@router.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    # 1) Forward (session_id, user_message) to the orchestrator
    # 2) Return the assistant text in a stable schema for UI/clients
    result = flow_controller.handle_turn(req.session_id, req.user_message)
    return ChatResponse(session_id=req.session_id, assistant_message=result.assistant_message)
