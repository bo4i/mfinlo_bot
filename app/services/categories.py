from collections.abc import Mapping
from typing import Iterable

from sqlalchemy.orm import Session

from app.db import get_db
from app.db.models import Category, Subcategory


CATEGORIES_STRUCTURE: Mapping[str, Iterable[str]] = {
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


def ensure_categories_exist(db: Session | None = None) -> None:
    """Populate the database with the default IT categories and subcategories."""

    def _seed(session: Session) -> None:
        for category_name, subcategories in CATEGORIES_STRUCTURE.items():
            category = session.query(Category).filter(Category.name == category_name).first()
            if not category:
                category = Category(name=category_name)
                session.add(category)
                session.flush()

            for subcategory_name in subcategories:
                subcategory_exists = (
                    session.query(Subcategory)
                    .filter(
                        Subcategory.name == subcategory_name,
                        Subcategory.category_id == category.id,
                    )
                    .first()
                )
                if not subcategory_exists:
                    session.add(Subcategory(name=subcategory_name, category_id=category.id))

        session.commit()

    if db is not None:
        _seed(db)
        return

    with get_db() as db_session:
        _seed(db_session)