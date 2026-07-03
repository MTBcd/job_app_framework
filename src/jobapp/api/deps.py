"""API dependencies: DB session and current user.

Dev auth: in local env, `X-Dev-User-Email` header identifies (and lazily
creates) the user. Clerk JWT verification replaces this dependency when the
web app lands — routes never know the difference.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from jobapp.db import get_session
from jobapp.db.models import User
from jobapp.settings import get_settings

DbSession = Annotated[Session, Depends(get_session)]


def get_current_user(
    session: DbSession,
    x_dev_user_email: Annotated[str | None, Header()] = None,
) -> User:
    settings = get_settings()
    if settings.app_env == "local" and x_dev_user_email:
        user = session.scalars(
            select(User).where(User.email == x_dev_user_email)
        ).first()
        if user is None:
            user = User(
                clerk_user_id=f"dev_{x_dev_user_email}", email=x_dev_user_email
            )
            session.add(user)
            session.commit()
        return user
    raise HTTPException(status_code=401, detail="authentication required")


CurrentUser = Annotated[User, Depends(get_current_user)]
