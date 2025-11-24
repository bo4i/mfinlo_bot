import logging

from aiogram import Bot, Dispatcher
from sqlalchemy import inspect, text
from sqlalchemy.exc import OperationalError

from app.config import AHO_ADMIN_IDS, IT_ADMIN_IDS
from app.db import engine, get_db
from app.db.models import Admin, User

logger = logging.getLogger(__name__)


async def on_startup(dispatcher: Dispatcher, bot: Bot) -> None:
    _ensure_photo_column_exists()

    with get_db() as db:
        for admin_id in IT_ADMIN_IDS:
            admin_exists = db.query(Admin).filter(Admin.id == admin_id, Admin.admin_type == "IT_ADMIN").first()
            if not admin_exists:
                db.add(Admin(id=admin_id, admin_type="IT_ADMIN"))
            user_exists = db.query(User).filter(User.id == admin_id).first()
            if not user_exists:
                db.add(
                    User(
                        id=admin_id,
                        registered=True,
                        role="it_admin",
                        full_name=f"IT Admin {admin_id}",
                        phone_number="N/A",
                        organization="N/A",
                    )
                )
            elif user_exists.role != "it_admin":
                user_exists.role = "it_admin"
                user_exists.registered = True
            logger.info("IT-администратор %s добавлен/обновлен.", admin_id)

        for admin_id in AHO_ADMIN_IDS:
            admin_exists = db.query(Admin).filter(Admin.id == admin_id, Admin.admin_type == "AHO_ADMIN").first()
            if not admin_exists:
                db.add(Admin(id=admin_id, admin_type="AHO_ADMIN"))
            user_exists = db.query(User).filter(User.id == admin_id).first()
            if not user_exists:
                db.add(
                    User(
                        id=admin_id,
                        registered=True,
                        role="aho_admin",
                        full_name=f"AHO Admin {admin_id}",
                        phone_number="N/A",
                        organization="N/A",
                    )
            )
            elif user_exists.role != "aho_admin":
                user_exists.role = "aho_admin"
                user_exists.registered = True
            logger.info("АХО-администратор %s добавлен/обновлен.", admin_id)

        db.commit()
    logger.info("Администраторы успешно инициализированы в БД.")


def _ensure_photo_column_exists() -> None:
    try:
        with engine.connect() as connection:
            inspector = inspect(connection)
            columns = [column["name"] for column in inspector.get_columns("requests")]
            if "photo_file_id" not in columns:
                connection.execute(text("ALTER TABLE requests ADD COLUMN photo_file_id VARCHAR"))
                logging.info("Столбец photo_file_id добавлен в таблицу requests.")
    except OperationalError as exc:  # noqa: BLE001
        logging.error("Не удалось изменить структуру таблицы requests: %s", exc)