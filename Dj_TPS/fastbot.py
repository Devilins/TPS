import os
from datetime import datetime, timedelta
from typing import Optional

from dotenv import load_dotenv
import logging
from contextlib import asynccontextmanager

import asyncio
from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.fsm.storage.memory import MemoryStorage
from fastapi import FastAPI, HTTPException, Depends, status
import httpx
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

# Загрузка переменных окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class TokenManager:
    def __init__(self):
        self.access_token: Optional[str] = None
        self.refresh_token: Optional[str] = None
        self.expires_at: Optional[datetime] = None
        self.lock = asyncio.Lock()

    async def login(self) -> bool:
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    os.getenv("DJANGO_API_URL")+"token/",
                    data={
                        "username": os.getenv("TEL_BOT_USER"),
                        "password": os.getenv("TEL_BOT_PWD"),
                    }
                )
                response.raise_for_status()

                tokens = response.json()
                self.access_token = tokens["access"]
                self.refresh_token = tokens["refresh"]
                self.expires_at = datetime.now() + timedelta(seconds=290)  # 5 минут - 10 секунд
                return True
            except Exception as e:
                logger.error(f"Bot login failed: {e}")
                return False

    async def ensure_valid_token(self) -> bool:
        async with self.lock:
            if self.expires_at and datetime.now() < self.expires_at:
                return True

            if not self.refresh_token:
                return await self.login()

            try:
                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        os.getenv("DJANGO_API_URL")+"token/refresh/",
                        json={"refresh": self.refresh_token}
                    )
                    response.raise_for_status()

                    tokens = response.json()
                    self.access_token = tokens["access"]
                    self.expires_at = datetime.now() + timedelta(seconds=290)
                    return True
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 401:
                    logger.warning("Refresh token expired, re-login required")
                    return await self.login()
                else:
                    logger.error(f"Token refresh error: {e}")
                    return False
            except Exception as e:
                logger.error(f"Token refresh failed: {e}")
                return False


# Инициализация объектов aiogram
bot = Bot(token=os.getenv('TELEGRAM_BOT_TOKEN'))
router = Router()
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

token_manager = TokenManager()


# Защита эндпоинта с помощью JWT
security = HTTPBearer()


async def authenticate(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> None:
    """Проверка JWT-токена."""
    if credentials.credentials != os.getenv("DJANGO_JWT_TOKEN"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or expired token",
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Инициализация бота
    dp.include_router(router)

    # Первоначальная аутентификация
    if not await token_manager.login():
        raise RuntimeError("Initial authentication failed")

    # Фоновые задачи
    polling_task = asyncio.create_task(dp.start_polling(bot))
    refresh_task = asyncio.create_task(token_refresh_worker())
    logger.info("Bot started")

    yield

    # Очистка
    polling_task.cancel()
    refresh_task.cancel()

    try:
        await polling_task
        await refresh_task
    except asyncio.CancelledError:
        pass

    await dp.storage.close()
    await bot.session.close()


async def token_refresh_worker():
    while True:
        await asyncio.sleep(60)  # Проверка каждую минуту
        await token_manager.ensure_valid_token()

# Инициализация FastAPI
app = FastAPI(lifespan=lifespan)


# --- Обработчики Telegram ---
@router.message(Command('start'))
async def handle_start(message: Message):
    await message.answer("Привет! Я бот для мониторинга. Используй /mon_events")


@router.message(Command("mon_events"))
async def handle_status(message: Message):
    if not await token_manager.ensure_valid_token():
        await message.answer("❌ Ошибка авторизации")
        return

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                os.getenv("DJANGO_API_URL")+'mon/',
                headers={"Authorization": f"Bearer {token_manager.access_token}"}
            )
            response.raise_for_status()
            data = response.json()
            status_text = "\n".join([
                                f"{item['date_updated']}\n{item['event_type']}: {item['event_message']}\n"
                                f"Статус - {item['status']}, Решено - {item['solved']}"
                                for item in data])
            await message.answer(f"📊 События мониторинга:\n\n{status_text}")
        except Exception as e:
            logger.error(f"Django API error: {e}")
            await message.answer("⚠️ Ошибка получения данных")


# --- Эндпоинт для триггеров из Django ---
# @app.post("/notify/")
# async def send_notification(message: str):
#     try:
#         await bot.send_message(
#             chat_id=os.getenv('ADMIN_CHAT_ID'),
#             text=f"🔔 Уведомление: {message}"
#         )
#         return {"status": "success"}
#     except Exception as e:
#         logger.error(f"Notification failed: {e}")
#         raise HTTPException(status_code=500, detail="Notification failed")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
