from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import accounts
from ..db import get_db
from ..deps import get_llm
from ..llm.base import LLMClient, LLMError
from ..models import ChatMessage
from ..services.chat import run_chat

router = APIRouter(prefix="/api/chat", tags=["chat"])


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


class ChatOut(BaseModel):
    reply: str
    cards: list[dict] = []
    degraded: bool = False


@router.post("", response_model=ChatOut)
def chat(body: ChatIn, db: Session = Depends(get_db), llm: LLMClient = Depends(get_llm)):
    allowance = accounts.chat_allowance(db, db.info["user"]) if db.info.get("user") else {"limit": None}
    if allowance["limit"] is not None and allowance["used"] >= allowance["limit"]:
        raise HTTPException(429, f"You've used today's {allowance['limit']} coach messages. Logging with the buttons "
                                 "still works, and the limit resets tomorrow. You can also add your own free Gemini "
                                 "key in Account to remove the limit.")
    result = run_chat(db, llm, body.message.strip())
    return ChatOut(reply=result.reply, cards=result.cards, degraded=result.degraded)


@router.get("/history")
def history(limit: int = 50, db: Session = Depends(get_db)):
    rows = db.scalars(select(ChatMessage).order_by(ChatMessage.id.desc()).limit(min(limit, 200))).all()
    return [{"role": r.role, "content": r.content, "at": r.created_at.isoformat()} for r in reversed(rows)]
