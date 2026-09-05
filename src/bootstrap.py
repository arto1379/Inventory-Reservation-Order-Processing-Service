"""
One-shot startup bootstrap: ensures a default ADMIN user exists.

Run once before the API starts (see docker-compose.yml's `api` service
command). Lets a fresh `docker compose up` be immediately usable end-to-end
-- log in as DEFAULT_ADMIN_EMAIL/DEFAULT_ADMIN_PASSWORD to get an ADMIN
token without any manual setup step. Idempotent: safe to run on every
container start, since it only creates the user if it doesn't already exist.
"""
import logging

from src.config import settings
from src.core.ids import generate_id
from src.core.security import hash_password
from src.database import SessionLocal
from src.logging_config import configure_logging
from src.models.enums import UserRole
from src.models.user import User
from src.repositories import user_repository

logger = logging.getLogger(__name__)


def ensure_default_admin() -> None:
    db = SessionLocal()
    try:
        if user_repository.get_by_email(db, settings.default_admin_email) is not None:
            logger.info("Default admin already exists, skipping bootstrap")
            return
        user = User(
            id=generate_id("user"),
            email=settings.default_admin_email,
            hashed_password=hash_password(settings.default_admin_password),
            role=UserRole.ADMIN,
        )
        user_repository.create(db, user)
        db.commit()
        logger.info("Created default admin user: %s", settings.default_admin_email)
    finally:
        db.close()


if __name__ == "__main__":
    configure_logging()
    ensure_default_admin()
