from aiogram import F, Router
from aiogram.types import Message

router = Router()


@router.message(F.text == "Портал бюджетной системы Липецкой области")
async def send_website_link(message: Message) -> None:
    await message.answer("[Портал бюджетной системы Липецкой области](https://ufin48.ru)", parse_mode="MarkdownV2")