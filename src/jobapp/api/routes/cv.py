"""CV upload and retrieval (text paste for now; PDF/DOCX extraction in M2)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from jobapp.api.deps import CurrentUser, DbSession
from jobapp.db.models import Document

router = APIRouter(prefix="/cv", tags=["cv"])


class CvIn(BaseModel):
    content_text: str = Field(min_length=50)
    filename: str = ""


@router.post("", status_code=201)
def upload_cv(payload: CvIn, user: CurrentUser, session: DbSession) -> dict:
    existing = session.scalars(
        select(Document).where(Document.user_id == user.id, Document.kind == "cv")
    ).first()
    if existing:
        existing.content_text = payload.content_text
        existing.filename = payload.filename
        existing.parsed_profile = {}
        existing.parse_warnings = ["reparse_pending"]
        document = existing
    else:
        document = Document(
            user_id=user.id,
            kind="cv",
            filename=payload.filename,
            content_text=payload.content_text,
            parse_warnings=["parse_pending"],
        )
        session.add(document)
    session.commit()
    return {"id": document.id}


@router.get("")
def get_cv(user: CurrentUser, session: DbSession) -> dict:
    document = session.scalars(
        select(Document).where(Document.user_id == user.id, Document.kind == "cv")
    ).first()
    if document is None:
        raise HTTPException(status_code=404, detail="no CV uploaded")
    return {
        "id": document.id,
        "filename": document.filename,
        "content_text": document.content_text,
        "parsed_profile": document.parsed_profile,
        "parse_warnings": document.parse_warnings,
    }
