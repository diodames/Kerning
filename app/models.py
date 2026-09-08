from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.db import Base


def _utcnow():
    return datetime.now(timezone.utc)


def _uuid():
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    timezone: Mapped[str] = mapped_column(String(64), default="Europe/Prague")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class Session(Base):
    __tablename__ = "sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    expires: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class MagicLink(Base):
    __tablename__ = "magic_links"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    email: Mapped[str] = mapped_column(String(255), index=True)
    expires: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Profile(Base):
    __tablename__ = "profiles"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class Story(Base):
    __tablename__ = "stories"
    __table_args__ = (UniqueConstraint("key", "user_id", name="stories_key_user"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(512), index=True)
    user_id: Mapped[str] = mapped_column(String(36), default="", index=True)
    url: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text, default="")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at_i: Mapped[int] = mapped_column(Integer, default=0, index=True)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class UserDigest(Base):
    __tablename__ = "user_digests"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    generated_at: Mapped[str] = mapped_column(String(64), default="")
    cadences: Mapped[dict] = mapped_column(JSON, default=dict)


class FeedCache(Base):
    __tablename__ = "feed_cache"
    kind: Mapped[str] = mapped_column(String(16), primary_key=True)
    handle: Mapped[str] = mapped_column(String(255), primary_key=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    kind: Mapped[str] = mapped_column(String(16), index=True)
    user_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    force: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str] = mapped_column(Text, default="")
    not_before: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    locked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
