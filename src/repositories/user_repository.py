"""Data access for the `users` table."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models.user import User


def get_by_id(db: Session, user_id: str) -> User | None:
    return db.get(User, user_id)


def get_by_email(db: Session, email: str) -> User | None:
    return db.execute(select(User).where(User.email == email)).scalar_one_or_none()


def create(db: Session, user: User) -> User:
    db.add(user)
    db.flush()
    return user
