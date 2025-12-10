from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from app.config import DATABASE_URL

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def _migrate_schema() -> None:
    inspector = inspect(engine)

    if "categories" in inspector.get_table_names():
        category_columns = {column["name"] for column in inspector.get_columns("categories")}
        if "request_type" not in category_columns:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE categories ADD COLUMN request_type VARCHAR"))
                connection.execute(
                    text("UPDATE categories SET request_type = 'IT' WHERE request_type IS NULL")
                )


    if "users" in inspector.get_table_names():
        user_columns = {column["name"] for column in inspector.get_columns("users")}
        if "user_guide_shown" not in user_columns:
            with engine.begin() as connection:
                connection.execute(
                    text("ALTER TABLE users ADD COLUMN user_guide_shown BOOLEAN DEFAULT 0")
                )
                connection.execute(
                    text(
                        "UPDATE users SET user_guide_shown = 1 WHERE registered = 1 AND user_guide_shown IS NULL"
                    )
                )

    if "requests" in inspector.get_table_names():
        request_columns = {column["name"] for column in inspector.get_columns("requests")}
        if "admin_message_map" not in request_columns:
            with engine.begin() as connection:
                connection.execute(
                    text("ALTER TABLE requests ADD COLUMN admin_message_map VARCHAR")
                )

@contextmanager
def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

_migrate_schema()
from app.db import models  # noqa: E402  pylint: disable=wrong-import-position

Base.metadata.create_all(bind=engine)