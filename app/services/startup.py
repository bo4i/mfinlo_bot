import logging

from aiogram import Bot, Dispatcher

from app.config import AHO_ADMIN_IDS, IT_ADMIN_IDS
from app.db import get_db
from app.db.models import Admin, User

logger = logging.getLogger(__name__)


async def on_startup(dispatcher: Dispatcher, bot: Bot) -> None:
    db = next(get_db())

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
    db.close()
    logger.info("Администраторы успешно инициализированы в БД.")