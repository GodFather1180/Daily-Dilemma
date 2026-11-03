from __future__ import annotations

from typing import Optional, List, Tuple
from pydantic import BaseModel
from sqlalchemy import (
    select,
    insert,
    delete,
    String,
    Integer,
    Index,
    func,
    or_,
)
from sqlalchemy.orm import declarative_base, Session, mapped_column, Mapped
from fastapi import Depends
from sqlalchemy.exc import IntegrityError

from shared.database import get_db


####################
# SQLAlchemy model
####################

Base = declarative_base()


class User(Base):
    """
    Database model for users.
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Keep 'name' unique and explicitly indexed with a named index (tests require this)
    name: Mapped[str] = mapped_column(String, nullable=False)
    # Email is optional but must be unique if present
    email: Mapped[Optional[str]] = mapped_column(String, unique=True, nullable=True)
    # Store a hash when password is provided (never return this through the API)
    password_hash: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # User tier for rate limiting (default 1)
    tier: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


# Explicit, named index that tests look for; also enforces uniqueness of name.
Index("ix_users_name", User.name, unique=True)


####################
# Repository
####################


class UserRepository:
    """
    Controls manipulation of the users table.
    """

    def __init__(self, session: Session):
        self.session = session

    async def create(
        self,
        name: str,
        email: Optional[str] = None,
        password: Optional[str] = None,
        tier: int = 1,
    ) -> User:
        """
        Create a user (simple if only name; 'rich' if email/password provided).
        Raises IntegrityError on duplicate name or email.
        """
        import bcrypt

        password_hash = None
        if password:
            password_hash = bcrypt.hashpw(
                password.encode("utf-8"), bcrypt.gensalt()
            ).decode("utf-8")

        try:
            # Avoid RETURNING on SQLite to prevent "SQL statements in progress"
            self.session.execute(
                insert(User).values(
                    name=name,
                    email=email,
                    password_hash=password_hash,
                    tier=tier,
                )
            )
            self.session.commit()

            # Fetch the created row in a clean statement
            created = self.session.execute(
                select(User).where(User.name == name).limit(1)
            ).scalar_one()
            return created

        except IntegrityError:
            self.session.rollback()
            raise

    async def delete(self, name: str) -> bool:
        """
        Delete a user by name. Returns True if a row was deleted; False otherwise.
        """
        try:
            result = self.session.execute(delete(User).where(User.name == name))
            deleted = (result.rowcount or 0) > 0
            if deleted:
                self.session.commit()
            else:
                self.session.rollback()
            return deleted
        except Exception:
            self.session.rollback()
            raise

    async def get_all(self) -> List[User]:
        # Retained for backward-compat, but avoid using this for UI paths
        return self.session.scalars(select(User).order_by(User.id.asc())).all()

    async def list_paginated(
        self,
        limit: int,
        offset: int,
        q: Optional[str] = None,
    ) -> Tuple[List[User], int]:
        """
        Return a stable, paginated page ordered by id ASC, and the total count.
        Optional case-insensitive search across name/email.
        """
        base = select(User)
        count_base = select(func.count()).select_from(User)

        if q:
            # Case-insensitive contains on name/email (portable across SQLite/Postgres)
            pattern = f"%{q.lower()}%"
            cond = or_(
                func.lower(User.name).like(pattern),
                func.lower(User.email).like(pattern),
            )
            base = base.where(cond)
            count_base = count_base.where(cond)

        total = self.session.execute(count_base).scalar_one()
        rows = (
            self.session.execute(
                base.order_by(User.id.asc()).limit(limit).offset(offset)
            )
            .scalars()
            .all()
        )
        return rows, total

    async def get_by_name(self, name: str) -> Optional[User]:
        stmt = select(User).where(User.name == name).limit(1)
        return self.session.execute(stmt).scalar_one_or_none()


def get_user_repository(db: Session = Depends(get_db)) -> UserRepository:
    return UserRepository(db)


####################
# Pydantic schemas
####################


class UserCreateSchema(BaseModel):
    """
    Input model for creating a user.
    """

    name: str
    email: Optional[str] = None
    password: Optional[str] = None
    tier: Optional[int] = 1


class UserSchema(BaseModel):
    """
    Output model for API responses (never exposes password fields).
    """

    id: Optional[int] = None
    name: str
    email: Optional[str] = None
    tier: int = 1

    @classmethod
    def from_db_model(cls, user: Optional[User]) -> Optional["UserSchema"]:
        if user is None:
            return None
        return cls(id=user.id, name=user.name, email=user.email, tier=user.tier)
