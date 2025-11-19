import asyncio
import logging

from aiogram import Bot, Dispatcher

from app.config import BOT_TOKEN
from app.routers import admins, misc, registration, requests, users
from app.services import on_startup

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(name)s - %(message)s")
logger = logging.getLogger(__name__)


def build_dispatcher(bot: Bot) -> Dispatcher:
    dp = Dispatcher()
    dp.include_router(registration.router)
    dp.include_router(requests.router)
    dp.include_router(admins.router)
    dp.include_router(users.router)
    dp.include_router(misc.router)

    dp.startup.register(lambda: on_startup(dp, bot))
    return dp


async def main() -> None:
    bot = Bot(token=BOT_TOKEN)
    dp = build_dispatcher(bot)
    logger.info("Бот запущен. Начинаю опрос...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())