"""Behind the email draft card: save edits, mark copied, and send after the person confirms."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth import current_user
from app.comms import email
from app.db import get_conn

router = APIRouter(prefix="/api/app/comms")


class DraftEdit(BaseModel):
    subject: str | None = None
    body: str | None = None
    recipient: dict | None = None
    status: str | None = None  # draft or copied


class SendReq(BaseModel):
    id: int


@router.patch("/draft/{draft_id}")
def edit_draft(draft_id: int, body: DraftEdit, user=Depends(current_user)):
    row = email.update(user, draft_id, body.model_dump())
    if not row:
        raise HTTPException(404, "draft not found")
    return row


@router.post("/send")
def send_draft(body: SendReq, user=Depends(current_user), conn=Depends(get_conn)):
    return email.send(conn, user, body.id)  # the person already confirmed in the card
