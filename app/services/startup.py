import logging

from aiogram import Bot, Dispatcher
from sqlalchemy import inspect, text
from sqlalchemy.exc import OperationalError

from app.config import AHO_ADMIN_IDS, IT_ADMIN_IDS
from app.db import engine, get_db
from app.db.models import Admin, Category, Subcategory, User

logger = logging.getLogger(__name__)


async def on_startup(dispatcher: Dispatcher, bot: Bot) -> None:
    _ensure_request_columns_exist()
    _ensure_categories_exist()

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


def _ensure_request_columns_exist() -> None:
    required_columns = {
        "photo_file_id": "VARCHAR",
        "comment": "VARCHAR",
        "attachment_type": "VARCHAR",
        "car_start_at": "TIMESTAMP",
        "car_end_at": "TIMESTAMP",
        "car_location": "VARCHAR",
        "category_id": "INTEGER",
        "subcategory_id": "INTEGER",
        "planned_date": "TIMESTAMP",

    }
    try:
        with engine.connect() as connection:
            inspector = inspect(connection)
            existing_columns = {column["name"] for column in inspector.get_columns("requests")}
            for column_name, column_type in required_columns.items():
                if column_name not in existing_columns:
                    connection.execute(text(f"ALTER TABLE requests ADD COLUMN {column_name} {column_type}"))
                    logging.info("Столбец %s добавлен в таблицу requests.", column_name)
    except OperationalError as exc:  # noqa: BLE001
        logging.error("Не удалось изменить структуру таблицы requests: %s", exc)

    def _ensure_categories_exist() -> None:
        categories_structure = {
            "Рабочие места и оборудование": [
                "Настройка нового ПК/ноутбука",
                "Зависания ПК",
                "Установка подключения из дома",
                "Проблемы с монитором/клавиатурой/мышью",
                "Забыли пароль",
                "Не запускается компьютер",
                "Ошибки операционной системы (Синий экран)",
                "Настройка рабочего места (перемещение, замена)",
            ],
            "Принтеры и МФУ": [
                "Не печатает/Не сканирует",
                "Подключение нового принтера / МФУ",
                "Замятие бумаги",
                "Закончился картридж / тонер",
                "Ошибки печати (полосы, смазано)",
            ],
            "ПО и сервисы": [
                "БКС/Next: Проблемы/ошибки",
                "Свод: Проблемы/ошибки",
                "Проект:  Проблемы/ошибки",
                "Торги: Проблемы/ошибки",
                "ЕЦИС/БГУ/ЗиКГУ проблемы/ошибки",
                "СУФД: Проблемы/ошибки",
                "Добавление/изменение ролей/настрока прав",
                "Запрос выгрузки/загрузки данных",
                "Запрос аналитики/отчета/бизнес-процесса",
                "Запрос настроки ПО/нового функционала",
                "Установка/настройка Бюджет-/Проект-/Свод-смарт",
                "Установка/настройка ЕЦИС БГУ, ЗиКГУ и прочее",
                "Установка офисного пакета (MS Office/LibreOffice)",
                "Нужна консультация по использованию ПО",
                "Сбои после обновлений",
            ],
            "Почта и Интернет": [
                "Настройка почты",
                "Не приходят/не отправляются письма",
                "Переполнен почтовый ящик",
                "Доступ к общим почтовым ящикам",
                "Нет подключения к интернету",
                "Не работает удаленное подключение",
            ],
            "Аккаунты, доступы, пароли и информационная безопасность": [
                "Забыли пароль - сброс/восстановление пароля",
                "Создание нового пользователя",
                "Доступ к почтовому ящику",
                "Доступ к сетевым папкам",
                "Подозрительное письмо / фишинг",
                "Срабатывание антивируса",
                "Запрос на открытие заблокированного сайта",
            ],
        }

        with get_db() as db:
            for category_name, subcategories in categories_structure.items():
                category = db.query(Category).filter(Category.name == category_name).first()
                if not category:
                    category = Category(name=category_name)
                    db.add(category)
                    db.flush()
                for subcategory_name in subcategories:
                    subcategory_exists = (
                        db.query(Subcategory)
                        .filter(
                            Subcategory.name == subcategory_name,
                            Subcategory.category_id == category.id,
                        )
                        .first()
                    )
                    if not subcategory_exists:
                        db.add(Subcategory(name=subcategory_name, category_id=category.id))
            db.commit()