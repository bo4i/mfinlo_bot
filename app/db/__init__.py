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
        existing_columns = {column["name"] for column in inspector.get_columns("categories")}
        if "request_type" not in existing_columns:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE categories ADD COLUMN request_type VARCHAR"))
                connection.execute(
                    text("UPDATE categories SET request_type = 'IT' WHERE request_type IS NULL")
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