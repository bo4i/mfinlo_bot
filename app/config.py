import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не найден в переменных окружения. Создайте файл .env с BOT_TOKEN=ВАШ_ТОКЕН_БОТА")

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./bot.db")

IT_ADMIN_IDS = [721618593]
AHO_ADMIN_IDS = [721618593]

PREDEFINED_ORGANIZATIONS = [
    "Министерство финансов Липецкой области",
    "ОКУ «Центра бухгалтерского учета» г.Липецк",
]

ORGANIZATIONS_NEEDING_OFFICE_NUMBER = {
    "Министерство финансов Липецкой области",
    "ОКУ «Центра бухгалтерского учета» г.Липецк",
}