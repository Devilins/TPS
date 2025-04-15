import os
import django
from django.conf import settings
from django.db.models import Sum

# Инициализация настроек джанги
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Dj_TPS.settings")
django.setup()

import pytz
from datetime import datetime, timedelta
from typing import Optional

from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from asgiref.sync import sync_to_async
from dotenv import load_dotenv
import logging
from contextlib import asynccontextmanager

import asyncio
from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import Command
from aiogram.types import Message, KeyboardButton, ReplyKeyboardMarkup
from aiogram.fsm.storage.memory import MemoryStorage
from fastapi import FastAPI, HTTPException, Depends, status
import httpx
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from tph_system.models import TelegramUser, Sales, Store
from django.contrib.auth.models import User
from django.core.exceptions import ObjectDoesNotExist

# Загрузка переменных окружения
load_dotenv()

# asyncio Lock (чтобы несколько корутин не изменяли данные одновременно)
lock = asyncio.Lock()

#Подтягиваем timezone из settings
tz = pytz.timezone(settings.TIME_ZONE)

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Инициализация объектов aiogram
bot = Bot(token=os.getenv('TELEGRAM_BOT_TOKEN'))
router = Router()
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Защита эндпоинта с помощью JWT
security = HTTPBearer()


async def auth_check(tel_user_id):
    url = f"{os.getenv('DJANGO_API_URL')}tuser/"
    params = {"telegram_id": str(tel_user_id)}

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params)
            response.raise_for_status()

            t_user = response.json()
            erp_user = t_user[0]
            # logger.info(f"ERP_USER - {erp_user}")

            return erp_user
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 401:
            logger.warning("You are not auth to get tuser")
            return None
        else:
            logger.error(f"Get tuser error: {e}")
            return None
    except Exception as e:
        logger.error(f"Get telegram user failed: {e}")
        return None


async def ensure_valid_token(t_user):
    if datetime.fromisoformat(t_user["edited_at"]) > tz.localize(datetime.now())- timedelta(seconds=290):
        logger.info("Последний раз авторизовывались менее 5 минут назад.")
        return t_user

    if datetime.fromisoformat(t_user["edited_at"]) < tz.localize(datetime.now()) - timedelta(days=1):
        logger.info("Последний раз авторизовывались больше чем 24 часа назад.")
        return None

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                os.getenv("DJANGO_API_URL")+"token/refresh/",
                json={"refresh": t_user["refresh_token"]}
            )
            response.raise_for_status()

            tokens = response.json()

            url = os.getenv("DJANGO_API_URL") + "tuser/" + str(t_user["id"]) + "/"
            data = {
                    "access_token": tokens["access"],
                    "telegram_id": t_user["telegram_id"]
                }

            put_response = await client.put(url, data=data)
            put_response.raise_for_status()

            upd_t_user = await auth_check(t_user["telegram_id"])

            return upd_t_user

    except httpx.HTTPStatusError as e:
        if e.response.status_code == 401:
            logger.warning("Refresh token expired, re-login required")
            return None
        else:
            logger.error(f"Token refresh error: {e}. Тело ошибки: {e.response.text}")
            return None
    except Exception as e:
        logger.error(f"Token refresh failed: {e}")
        return None


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Инициализация бота
    dp.include_router(router)

    # Фоновые задачи
    polling_task = asyncio.create_task(dp.start_polling(bot))
    logger.info("Bot started")

    yield

    # Очистка
    polling_task.cancel()

    try:
        await polling_task
    except asyncio.CancelledError:
        pass

    await dp.storage.close()
    await bot.session.close()


# Инициализация FastAPI
app = FastAPI(lifespan=lifespan)


# --- Обработчики Telegram ---
class LoginState(StatesGroup):
    waiting_for_username = State()
    waiting_for_password = State()


kb = [
    [
        KeyboardButton(text="Мой пользователь"),
        KeyboardButton(text="Кассы за сегодня"),
        KeyboardButton(text="Системные ошибки")
    ],
]

keyboard_main = ReplyKeyboardMarkup(
    keyboard=kb,
    resize_keyboard=True,
    input_field_placeholder="О чем вам рассказать?"
)

@router.message(Command('start'))
async def handle_start(message: Message):
    await message.answer("👋 Привет! Я бот для мониторинга ERP системы. Чтобы со мной работать, тебе надо "
                         "авторизоваться 🤌 (Команда /login)")

@router.message(Command('stop'))
async def handle_stop(message: Message):
    t_user = await auth_check(message.from_user.id)
    if t_user is not None:
        async with lock:
            await sync_to_async(t_user.delete)()
            await message.answer("🤙 Вы успешно разлогинены. До новых встреч!")
    else:
        await message.answer("🤙 Вы не проходили авторизацию (/login)")

@router.message(Command("login"))
async def cmd_login(message: Message, state: FSMContext):
    await message.answer("Введите ваш логин:")
    await state.set_state(LoginState.waiting_for_username)

@router.message(LoginState.waiting_for_username)
async def process_username(message: Message, state: FSMContext):
    await state.update_data(username=message.text)
    await message.answer("Теперь введите пароль:")
    await state.set_state(LoginState.waiting_for_password)

@router.message(LoginState.waiting_for_password)
async def process_password(message: Message, state: FSMContext):
    user_data = await state.get_data()
    username = user_data['username']
    password = message.text

    # Отправляем запрос к Django API
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                os.getenv("DJANGO_API_URL") + "token/",
                data={"username": username, "password": password}
            )
            response.raise_for_status()

            tokens = response.json()

            # Сохраняем токены в базе
            try:
                user = await sync_to_async(User.objects.get)(username=username)
            except ObjectDoesNotExist:
                await message.answer(f"Пользователя {username} не существует!")

            await sync_to_async(TelegramUser.objects.update_or_create)(
                telegram_id=message.from_user.id,
                defaults={
                    'user': user,
                    'access_token': tokens['access'],
                    'refresh_token': tokens['refresh']
                }
            )

            await message.answer("✅ Вы успешно авторизованы!", reply_markup=keyboard_main)

        except httpx.HTTPStatusError as e:
            await message.answer("❌ Неверный логин или пароль")
        finally:
            await state.clear()

@router.message(F.text.lower() == "мой пользователь")
async def my_user(message: Message):
    log_user = await auth_check(message.from_user.id)
    if log_user is not None:
        log_user = log_user["user"]
        await message.answer(f"🤌 Твой пользователь - {log_user["username"]} ({log_user["first_name"]} {log_user["last_name"]})",
                             reply_markup=keyboard_main)
    else:
        await message.answer("🖐 Чтобы со мной работать, тебе надо авторизоваться 🤌 (Команда /login)")

@router.message(F.text.lower() == "кассы за сегодня")
async def cash_box(message: Message):
    sls = await sync_to_async(
        lambda: list(Sales.objects.filter(date=datetime.now()).values('store').annotate(store_sum=Sum('sum')))
    )()
    st = await sync_to_async(Store.objects.values)('id', 'name')
    dic = {}
    for i in sls:
        dic[st.get(id=i['store'])['name']] = i['store_sum']
    cashbx_all = sum(dic.values())

    msg = "📊 Кассы точек за сегодня:\n\n"
    for store, summ in dic.items():
        msg += f"{store}: {summ} ₽\n"
    msg += f"\nИтого за день: {cashbx_all}"
    await message.answer(msg, reply_markup=keyboard_main)

@router.message(F.text.lower() == "системные ошибки")
async def sys_errors(message: Message):
    log_user = await auth_check(message.from_user.id)

    if log_user is None:
        await message.answer("🖐 Чтобы со мной работать, тебе надо авторизоваться 🤌 (Команда /login)")
        return

    checked_user = await ensure_valid_token(log_user)

    if checked_user is not None:
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(
                    os.getenv("DJANGO_API_URL")+'mon/',
                    headers={"Authorization": f"Bearer {checked_user["access_token"]}"}
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
    else:
        await message.answer("🖐 Время авторизации истекло, авторизуйтесь еще раз 🤌 (Команда /login)")


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
