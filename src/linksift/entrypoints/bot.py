import asyncio
import logging
import sys
import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable
from html import escape
from typing import Any

from aiogram import BaseMiddleware, Bot, Dispatcher, Router
from aiogram.filters import Command
from aiogram.types import BotCommand, Message, TelegramObject

from linksift.application.ingestion import (
    InvalidInputError,
    InvalidUrlError,
    MaterialIngestionService,
    MultipleUrlsError,
    TextTooLongError,
    status_label,
)
from linksift.application.repositories import DatabaseOperationError
from linksift.config import Settings
from linksift.infrastructure.database.engine import create_database_engine, create_session_factory
from linksift.infrastructure.database.repositories import SqlAlchemyMaterialRepository

logger = logging.getLogger(__name__)

START_TEXT = """LinkSift готов.

Отправь одну ссылку или текст — я сохраню материал для обработки.

/history — последние материалы
/help — справка"""

HELP_TEXT = """Можно отправить одну HTTP/HTTPS-ссылку или обычный текст.

Повторная ссылка не создаёт дубликат. /history показывает только твои материалы.

AI-анализ будет подключён следующим этапом. Файлы пока не поддерживаются."""

UNSUPPORTED_TEXT = (
    "Пока поддерживаются только текст и одна ссылка. "
    "Загрузка файлов будет добавлена следующим этапом."
)


class PrivateChatMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, Message):
            return None
        if event.chat.type != "private" or event.from_user is None or event.from_user.is_bot:
            return None
        return await handler(event, data)


class RateLimitMiddleware(BaseMiddleware):
    def __init__(self, *, limit: int = 10, window_seconds: float = 60) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._events: dict[int, deque[float]] = defaultdict(deque)

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, Message) or event.from_user is None:
            return await handler(event, data)
        if event.text is None or event.text.startswith("/"):
            return await handler(event, data)

        now = time.monotonic()
        events = self._events[event.from_user.id]
        while events and events[0] <= now - self.window_seconds:
            events.popleft()
        if len(events) >= self.limit:
            await event.answer("Слишком много запросов. Попробуй через минуту.")
            return None
        events.append(now)
        return await handler(event, data)


def _history_text(materials: list[Any]) -> str:
    if not materials:
        return "История пока пуста. Отправь ссылку или текст."
    items = ["Последние материалы:"]
    for index, material in enumerate(materials, start=1):
        display = material.title or material.source_url or material.source_text or "Без названия"
        display = " ".join(display.split())
        if len(display) > 180:
            display = f"{display[:177]}..."
        items.append(
            f"{index}. {escape(material.status)} · {escape(material.source_type)}\n"
            f"   {escape(display)}"
        )
    return "\n\n".join(items)


def create_dispatcher(service: MaterialIngestionService) -> Dispatcher:
    dispatcher = Dispatcher()
    router = Router()
    router.message.outer_middleware(PrivateChatMiddleware())
    router.message.outer_middleware(RateLimitMiddleware())

    @router.message(Command("start"))
    async def start(message: Message) -> None:
        await message.answer(START_TEXT)

    @router.message(Command("help"))
    async def help_command(message: Message) -> None:
        await message.answer(HELP_TEXT)

    @router.message(Command("history"))
    async def history(message: Message) -> None:
        if message.from_user is None:
            return
        try:
            materials = await service.history(owner_telegram_id=message.from_user.id, limit=10)
        except DatabaseOperationError:
            logger.warning(
                "telegram_history_failed user_id=%s error_code=database", message.from_user.id
            )
            await message.answer("База данных временно недоступна.")
            return
        except Exception:
            logger.error(
                "telegram_history_failed user_id=%s error_code=unexpected", message.from_user.id
            )
            await message.answer("Не удалось получить историю. Попробуй ещё раз.")
            return
        await message.answer(_history_text(materials), parse_mode="HTML")

    @router.message(lambda message: message.text is not None)
    async def ingest_text(message: Message) -> None:
        if message.from_user is None or message.text is None:
            return
        user_id = message.from_user.id
        try:
            result = await service.ingest(owner_telegram_id=user_id, text=message.text)
        except MultipleUrlsError:
            await message.answer("Отправь, пожалуйста, одну ссылку за сообщение.")
            return
        except TextTooLongError:
            await message.answer("Текст слишком длинный. Максимум — 20 000 символов.")
            return
        except InvalidUrlError:
            await message.answer("Ссылка имеет неподдерживаемый формат.")
            return
        except InvalidInputError:
            await message.answer(UNSUPPORTED_TEXT)
            return
        except DatabaseOperationError:
            logger.warning("telegram_ingestion_failed user_id=%s error_code=database", user_id)
            await message.answer("База данных временно недоступна.")
            return
        except Exception:
            logger.error("telegram_ingestion_failed user_id=%s error_code=unexpected", user_id)
            await message.answer("Не удалось сохранить материал. Попробуй ещё раз.")
            return

        material = result.material
        if not result.created:
            await message.answer(f"Этот материал уже сохранён.\n\nСтатус: {material.status}")
            return
        logger.info(
            "telegram_material_saved user_id=%s material_id=%s source_type=%s status=%s",
            user_id,
            material.id,
            material.source_type,
            material.status,
        )
        await message.answer(
            "Материал сохранён.\n\n"
            f"Тип: {material.source_type}\n"
            f"Статус: {status_label(material.status)}"
        )

    @router.message()
    async def unsupported(message: Message) -> None:
        await message.answer(UNSUPPORTED_TEXT)

    dispatcher.include_router(router)
    return dispatcher


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stdout,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    settings = Settings()
    token = settings.bot_token.get_secret_value()
    if not token:
        raise RuntimeError("LINKSIFT_BOT_TOKEN is not configured")

    engine = create_database_engine(settings.database_url)
    repository = SqlAlchemyMaterialRepository(create_session_factory(engine))
    service = MaterialIngestionService(repository)
    try:
        async with Bot(token=token) as bot:
            identity = await bot.get_me()
            logger.info(
                "telegram_bot_starting bot_id=%s username=%s", identity.id, identity.username
            )
            await bot.delete_webhook(drop_pending_updates=False)
            await bot.set_my_commands(
                [
                    BotCommand(command="start", description="Запустить LinkSift"),
                    BotCommand(command="help", description="Показать справку"),
                    BotCommand(command="history", description="Показать последние материалы"),
                ]
            )
            await create_dispatcher(service).start_polling(bot, close_bot_session=False)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
