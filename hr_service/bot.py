from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, ReplyKeyboardRemove
from candidate.database import get_connection
from core.config import settings
from datetime import datetime

# Состояния FSM
class AuthState(StatesGroup):
    waiting_for_code = State()

# Инициализация бота
bot = Bot(token=settings.bot.TELEGRAM_TOKEN)
dp = Dispatcher()

async def is_user_authorized(chat_id: int) -> bool:
    """Проверяет, авторизован ли пользователь"""
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT 1 FROM hr.candidate WHERE telegram_chat_id = %s",
                (chat_id,)
            )
            return bool(cursor.fetchone())

async def save_message(chat_id: int, text: str, is_from_admin: bool = False):
    """Сохраняет сообщение в базу данных с проверкой существования чата"""
    with get_connection() as conn:
        with conn.cursor() as cursor:
            try:
                # Сначала проверяем/создаем запись в telegram_chat
                cursor.execute("""
                    INSERT INTO comm.telegram_chat (
                        chat_id, 
                        chat_type,
                        created_at,
                        updated_at
                    ) VALUES (%s, %s, %s, %s)
                    ON CONFLICT (chat_id) DO NOTHING
                """, (
                    chat_id,
                    'private',
                    datetime.now(),
                    datetime.now()
                ))
                
                # Затем сохраняем сообщение
                cursor.execute("""
                    INSERT INTO comm.message (
                        chat_id, 
                        content, 
                        sender_type, 
                        sent_at, 
                        is_from_admin
                    ) VALUES (%s, %s, %s, %s, %s)
                """, (
                    chat_id,
                    text,
                    'admin' if is_from_admin else 'candidate',
                    datetime.now(),
                    is_from_admin
                ))
                conn.commit()
            except Exception as e:
                conn.rollback()
                raise e

# Команда /start - доступна без авторизации
@dp.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await message.answer(
        "🔑 Для доступа к системе введите код приглашения, "
        "который вы получили по email:",
        reply_markup=ReplyKeyboardRemove()
    )
    await state.set_state(AuthState.waiting_for_code)

# Обновленная функция обработки кода приглашения
@dp.message(AuthState.waiting_for_code, F.text)
async def process_invitation_code(message: Message, state: FSMContext):
    code = message.text.strip().upper()
    chat_id = message.chat.id

    with get_connection() as conn:
        with conn.cursor() as cursor:
            try:
                cursor.execute(
                    """
                    UPDATE hr.candidate 
                    SET telegram_chat_id = %s
                    WHERE invitation_code = %s
                    RETURNING first_name, last_name, candidate_uuid
                    """,
                    (chat_id, code)
                )
                
                if result := cursor.fetchone():
                    first_name, last_name, candidate_uuid = result
                    
                    # Создаем запись в telegram_chat с привязкой к кандидату
                    cursor.execute("""
                        INSERT INTO comm.telegram_chat (
                            chat_id, 
                            candidate_uuid,
                            chat_type,
                            created_at,
                            updated_at
                        ) VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT (chat_id) DO UPDATE
                        SET candidate_uuid = EXCLUDED.candidate_uuid
                    """, (
                        chat_id,
                        candidate_uuid,
                        'private',
                        datetime.now(),
                        datetime.now()
                    ))
                    
                    conn.commit()
                    
                    # Сохраняем приветственное сообщение
                    await save_message(
                        chat_id,
                        f"Пользователь {first_name} {last_name} авторизовался",
                        True
                    )
                    
                    await message.answer(
                        f"✅ Добро пожаловать, {first_name} {last_name}!\n"
                        "Теперь у вас есть доступ к системе.\n"
                        "Используйте /menu для просмотра возможностей."
                    )
                    await state.clear()
                else:
                    await message.answer(
                        "❌ Неверный код приглашения. Попробуйте еще раз или "
                        "обратитесь в поддержку.\n"
                        "Для повторного ввода кода используйте /start"
                    )
                    
            except Exception as e:
                conn.rollback()
                await message.answer(
                    "⚠️ Произошла ошибка. Пожалуйста, попробуйте позже."
                )
                await state.clear()

# Обработка всех текстовых сообщений (только для авторизованных)
@dp.message(F.text)
async def handle_text_messages(message: Message):
    chat_id = message.chat.id
    
    if not await is_user_authorized(chat_id):
        await message.answer(
            "🔐 Для доступа к системе сначала введите код приглашения "
            "через команду /start"
        )
        return
    
    # Сохраняем сообщение пользователя
    await save_message(chat_id, message.text, False)
    

# Команда /menu (только для авторизованных)
@dp.message(Command("menu"))
async def cmd_menu(message: Message):
    chat_id = message.chat.id
    
    if not await is_user_authorized(chat_id):
        await message.answer(
            "🔐 Для доступа к системе сначала введите код приглашения "
            "через команду /start"
        )
        return
    
    await save_message(chat_id, "/menu command", False)
    
    response = (
        "📋 Главное меню:\n"
        "- /docs - Мои документы\n"
        "- /profile - Мой профиль\n"
        "- /support - Поддержка"
    )
    await save_message(chat_id, response, True)
    await message.answer(response)

# Запуск бота
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())