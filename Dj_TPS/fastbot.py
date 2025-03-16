import os
from dotenv import load_dotenv
import logging
from contextlib import asynccontextmanager

import asyncio
from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.fsm.storage.memory import MemoryStorage
from fastapi import FastAPI, HTTPException, Depends
import httpx
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

# Загрузка переменных окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# Инициализация объектов aiogram
bot = Bot(token=os.getenv('TELEGRAM_BOT_TOKEN'))
router = Router()
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Асинхронный клиент для запросов к Django
security = HTTPBearer()
django_client = httpx.AsyncClient(
    base_url=os.getenv("DJANGO_API_URL"),
    headers={"Authorization": f"Bearer {os.getenv('DJANGO_JWT_TOKEN')}"}
)

# Добавьте проверку аутентификации для эндпоинта /notify
async def authenticate(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> None:
    if credentials.credentials != os.getenv("DJANGO_JWT_TOKEN"):
        raise HTTPException(status_code=401, detail="Invalid token")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Запускаем бота в фоне
    from aiogram import Dispatcher
    dp.include_router(router)

    polling_task = asyncio.create_task(dp.start_polling(bot))
    logger.info("Bot started")

    yield

    # Корректное завершение
    polling_task.cancel()
    try:
        await polling_task
    except asyncio.CancelledError:
        pass

    await dp.storage.close()
    await bot.session.close()
    await django_client.aclose()
    logger.info("Resources closed")

# Инициализация FastAPI
app = FastAPI(lifespan=lifespan)

# --- Обработчики Telegram ---
@router.message(Command('start'))
async def handle_start(message: Message):
    await message.answer("Привет! Я бот для мониторинга. Используй /mon_events")

@router.message(Command('mon_events'))
async def handle_events(message: Message):
    try:
        response = await django_client.get("/")
        response.raise_for_status()
        data = response.json()
        status_text = "\n".join([f"{item['date_updated']}\n{item['event_type']}: {item['event_message']}\nCтатус - {item['status']}, Решено - {item['solved']}" for item in data])
        await message.answer(f"📊 События мониторинга:\n{status_text}")
    except httpx.HTTPError as e:
        logger.error(f"Django API error: {e}")
        await message.answer("⚠️ Ошибка получения данных от сервера")
    except Exception as e:
        logger.exception("Unexpected error")
        await message.answer("❌ Внутренняя ошибка сервера")

# --- Эндпоинт для триггеров из Django ---
@app.post("/notify/")
async def send_notification(message: str,
                            auth: None = Depends(authenticate)  # Защита эндпоинта
                            ):
    try:
        await bot.send_message(
            chat_id=os.getenv('ADMIN_CHAT_ID'),
            text=f"🔔 Уведомление: {message}"
        )
        return {"status": "success"}
    except Exception as e:
        logger.error(f"Notification failed: {e}")
        raise HTTPException(status_code=500, detail="Notification failed")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
