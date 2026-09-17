import asyncio
from typing import Any

from aiogram import BaseMiddleware, Bot, Dispatcher, Router
from aiogram.filters import Command
from aiogram.types import Message, TelegramObject

from linksift.config import Settings


class AllowlistMiddleware(BaseMiddleware):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def __call__(self, handler: Any, event: TelegramObject, data: dict[str, Any]) -> Any:
        user = data.get("event_from_user")
        if user is None or not self.settings.allows(user.id):
            return None
        return await handler(event, data)


def create_dispatcher(settings: Settings) -> Dispatcher:
    dispatcher = Dispatcher()
    dispatcher.update.outer_middleware(AllowlistMiddleware(settings))
    router = Router()

    @router.message(Command("start", "help"))
    async def welcome(message: Message) -> None:
        await message.answer("LinkSift: окружение готово. Анализ медиа ещё не подключён.")

    @router.message()
    async def unavailable(message: Message) -> None:
        await message.answer("Обработка медиа пока не реализована. Файл не принят в обработку.")

    dispatcher.include_router(router)
    return dispatcher


async def main() -> None:
    settings = Settings()
    if not settings.bot_token.get_secret_value() or not settings.allowed_user_ids:
        raise RuntimeError("Set LINKSIFT_BOT_TOKEN and a non-empty LINKSIFT_ALLOWED_USER_IDS")
    async with Bot(token=settings.bot_token.get_secret_value()) as bot:
        await create_dispatcher(settings).start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
