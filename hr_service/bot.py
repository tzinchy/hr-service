from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton
from candidate.database import get_connection
from core.config import settings
from datetime import datetime
import pandas as pd
import uuid
import os
import tempfile
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from candidate.tg_service import is_user_authorized, process_bank_statement, save_message, create_required_documents, get_candidate_uuid_by_chat_id
from candidate.database import get_minio_client
import io
# Состояния FSM
class AuthState(StatesGroup):
    waiting_for_code = State()
    waiting_for_privacy_accept = State()
    document_upload = State()
    waiting_for_bank_data = State()

# Инициализация бота
bot = Bot(token=settings.bot.TELEGRAM_TOKEN)
dp = Dispatcher()

# Добавим логирование для отладки
import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)



@dp.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await message.answer(
        "🔑 Для доступа к системе введите код приглашения, "
        "который вы получили по email:",
        reply_markup=ReplyKeyboardRemove()
    )
    await state.set_state(AuthState.waiting_for_code)
    logger.info(f"User {message.chat.id} started the bot")

@dp.message(AuthState.waiting_for_code, F.text)
async def process_invitation_code(message: Message, state: FSMContext):
    code = message.text.strip().upper()
    chat_id = message.chat.id
    logger.info(f"Processing invitation code for user {chat_id}: {code}")

    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                # Проверяем, есть ли такой код
                cursor.execute(
                    """
                    SELECT candidate_uuid, first_name, last_name, agreement_accepted 
                    FROM hr.candidate 
                    WHERE invitation_code = %s
                    """,
                    (code,)
                )
                
                result = cursor.fetchone()
                
                if not result:
                    await message.answer(
                        "❌ Неверный код приглашения. "
                        "Попробуйте еще раз или обратитесь в поддержку."
                    )
                    return
                
                candidate_uuid, first_name, last_name, agreement_accepted = result
                
                # Обновляем telegram_chat_id
                cursor.execute(
                    """
                    UPDATE hr.candidate 
                    SET telegram_chat_id = %s
                    WHERE candidate_uuid = %s
                    """,
                    (chat_id, candidate_uuid)
                )
                
                # Создаем или обновляем запись в таблице чатов
                cursor.execute("""
                    INSERT INTO comm.telegram_chat (
                        chat_id, 
                        candidate_uuid,
                        chat_type,
                        created_at,
                        updated_at
                    ) VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (chat_id) DO UPDATE
                    SET candidate_uuid = EXCLUDED.candidate_uuid,
                        updated_at = EXCLUDED.updated_at
                """, (
                    chat_id,
                    candidate_uuid,
                    'private',
                    datetime.now(),
                    datetime.now()
                ))
                
                conn.commit()
                
                if agreement_accepted:
                    # Если политика уже принята, переходим к загрузке документов
                    await create_required_documents(candidate_uuid)
                    await message.answer(
                        f"✅ Добро пожаловать, {first_name} {last_name}!\n"
                        "Теперь вы можете загрузить необходимые документы.\n"
                        "Используйте /docs для управления документами."
                    )
                    await state.clear()
                else:
                    # Запрашиваем подтверждение политики
                    privacy_kb = InlineKeyboardMarkup(inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="✅ Принимаю",
                                callback_data="privacy_accept"
                            ),
                            InlineKeyboardButton(
                                text="❌ Отказываюсь",
                                callback_data="privacy_decline"
                            )
                        ]
                    ])
                    
                    await message.answer(
                        "📄 Пожалуйста, ознакомьтесь с нашей Политикой конфиденциальности:\n\n"
                        "1. Мы собираем только необходимые данные\n"
                        "2. Ваши данные защищены\n"
                        "3. Мы не передаем данные третьим лицам\n\n"
                        "Вы принимаете условия политики конфиденциальности?",
                        reply_markup=privacy_kb
                    )
                    await state.set_state(AuthState.waiting_for_privacy_accept)
                    await state.update_data(candidate_uuid=candidate_uuid)
                
                await save_message(
                    chat_id,
                    f"Пользователь {first_name} {last_name} авторизовался",
                    True
                )
    except Exception as e:
        logger.error(f"Error during invitation code processing: {e}")
        await message.answer(
            "⚠️ Произошла ошибка. Пожалуйста, попробуйте позже."
        )

@dp.callback_query(AuthState.waiting_for_privacy_accept, F.data == "privacy_accept")
async def accept_privacy(callback: types.CallbackQuery, state: FSMContext):
    chat_id = callback.message.chat.id
    data = await state.get_data()
    candidate_uuid = data['candidate_uuid']
    logger.info(f"User {chat_id} accepted privacy policy")
    
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    UPDATE hr.candidate 
                    SET agreement_accepted = TRUE,
                        agreement_accepted_at = NOW()
                    WHERE candidate_uuid = %s
                    RETURNING first_name, last_name
                """, (candidate_uuid,))
                
                result = cursor.fetchone()
                if not result:
                    await callback.message.answer("⚠️ Возникла ошибка. Пользователь не найден.")
                    await state.clear()
                    return
                    
                first_name, last_name = result
                
                # Создаем записи для требуемых документов
                await create_required_documents(candidate_uuid)
                
                conn.commit()
                
                await callback.message.edit_text(
                    f"✅ Спасибо, {first_name}! Вы приняли условия политики конфиденциальности.\n\n"
                    "Теперь вам необходимо загрузить следующие документы:\n"
                    "- Паспорт\n"
                    "- ИНН\n"
                    "- СНИЛС\n"
                    "- Выписка банка (Excel файл)\n\n"
                    "Используйте команду /docs для загрузки документов."
                )
                
                await save_message(
                    chat_id,
                    f"Пользователь {first_name} {last_name} принял политику конфиденциальности",
                    True
                )
                
                await state.clear()
                
    except Exception as e:
        logger.error(f"Error during privacy acceptance: {e}")
        await callback.message.answer(
            "⚠️ Произошла ошибка при сохранении. Пожалуйста, попробуйте позже."
        )

@dp.callback_query(AuthState.waiting_for_privacy_accept, F.data == "privacy_decline")
async def decline_privacy(callback: types.CallbackQuery, state: FSMContext):
    logger.info(f"User {callback.message.chat.id} declined privacy policy")
    await callback.message.edit_text(
        "❌ Вы отказались от принятия политики конфиденциальности. "
        "Для использования бота необходимо принять условия.\n\n"
        "Если вы передумаете, используйте команду /start"
    )
    await state.clear()

@dp.message(Command("docs"))
async def cmd_docs(message: Message, state: FSMContext):
    chat_id = message.chat.id
    logger.info(f"User {chat_id} requested docs")
    
    if not await is_user_authorized(chat_id):
        await message.answer(
            "🔐 Для доступа к системе сначала введите код приглашения "
            "через команду /start и примите политику конфиденциальности"
        )
        return
    
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                # Найдем кандидата
                cursor.execute("""
                    SELECT c.candidate_uuid, c.first_name, c.last_name 
                    FROM hr.candidate c
                    WHERE c.telegram_chat_id = %s
                """, (chat_id,))
                
                candidate = cursor.fetchone()
                if not candidate:
                    await message.answer("⚠️ Ваш профиль не найден. Обратитесь в поддержку.")
                    return
                
                candidate_uuid, first_name, last_name = candidate
                
                # Получим документы кандидата
                cursor.execute("""
                    SELECT d.document_id, t.name, d.status_id, t.template_id
                    FROM hr.candidate_document d
                    JOIN hr.document_template t ON d.template_id = t.template_id
                    WHERE d.candidate_id = %s
                    ORDER BY t.order_position
                """, (candidate_uuid,))
                
                documents = cursor.fetchall()
                
                if not documents:
                    # Если документов нет, создаем их
                    await create_required_documents(candidate_uuid)
                    
                    # Повторно получаем документы
                    cursor.execute("""
                        SELECT d.document_id, t.name, d.status_id, t.template_id
                        FROM hr.candidate_document d
                        JOIN hr.document_template t ON d.template_id = t.template_id
                        WHERE d.candidate_id = %s
                        ORDER BY t.order_position
                    """, (candidate_uuid,))
                    
                    documents = cursor.fetchall()
                
                # Создаем клавиатуру для выбора документа
                keyboard = []
                for doc in documents:
                    doc_id, doc_name, status_id, template_id = doc
                    status = "✅" if status_id == 2 else "❌"
                    keyboard.append([KeyboardButton(text=f"{status} {doc_name}")])
                
                keyboard.append([KeyboardButton(text="↩️ Назад в меню")])
                
                doc_kb = ReplyKeyboardMarkup(
                    keyboard=keyboard,
                    resize_keyboard=True
                )
                
                # Сохраняем информацию о документах в состоянии
                docs_info = {doc[1]: {"id": doc[0], "template_id": doc[3]} for doc in documents}
                await state.update_data(docs_info=docs_info)
                
                response = f"📂 {first_name}, выберите документ для загрузки:\n\n"
                for doc in documents:
                    doc_id, doc_name, status_id, _ = doc
                    status = "✅ Загружен" if status_id == 2 else "❌ Не загружен"
                    response += f"- {doc_name}: {status}\n"
                
                await message.answer(response, reply_markup=doc_kb)
                await save_message(chat_id, "Пользователю отображен список документов", True)
    except Exception as e:
        logger.error(f"Error displaying documents: {e}")
        await message.answer(
            "⚠️ Произошла ошибка при получении документов. Пожалуйста, попробуйте позже."
        )

@dp.message(F.text.startswith(("✅ ", "❌ ")))
async def handle_document_selection(message: Message, state: FSMContext):
    chat_id = message.chat.id
    
    if not await is_user_authorized(chat_id):
        await message.answer(
            "🔐 Для доступа к системе сначала введите код приглашения "
            "через команду /start и примите политику конфиденциальности"
        )
        return
    
    # Извлекаем название документа без статуса
    doc_name = message.text[2:].strip()
    
    # Получаем информацию о документах из состояния
    data = await state.get_data()
    docs_info = data.get('docs_info', {})
    
    if doc_name not in docs_info:
        await message.answer("Выберите документ из списка или используйте команду /docs")
        return
    
    doc_info = docs_info[doc_name]
    
    # Особая обработка для выписки банка
    if doc_name == "Выписка банка":
        await message.answer(
            "📊 Пожалуйста, загрузите Excel файл с выписками банка.\n"
            "Файл должен содержать следующие столбцы:\n"
            "- bank (название банка)\n"
            "- account_number (номер счета)\n"
            "- open_date (дата открытия)\n"
            "- close_date (дата закрытия)\n"
            "- account_type (тип счета)\n"
            "- status (статус счета)"
        )
        await state.set_state(AuthState.waiting_for_bank_data)
        await state.update_data(selected_doc=doc_info)
        return
    
    await message.answer(
        f"📄 Пожалуйста, загрузите файл для документа: {doc_name}"
    )
    await state.set_state(AuthState.document_upload)
    await state.update_data(selected_doc=doc_info)

@dp.message(F.text == "↩️ Назад в меню")
async def back_to_menu(message: Message, state: FSMContext):
    await cmd_menu(message, state)

@dp.message(AuthState.waiting_for_bank_data, F.document)
async def handle_bank_statement(message: Message, state: FSMContext):
    chat_id = message.chat.id
    document = message.document
    
    # Проверяем тип файла
    if not document.file_name.endswith(('.xlsx', '.xls')):
        await message.answer("❌ Пожалуйста, загрузите файл Excel (.xlsx или .xls)")
        return
    
    candidate_uuid = await get_candidate_uuid_by_chat_id(chat_id)
    if not candidate_uuid:
        await message.answer("⚠️ Ваш профиль не найден. Обратитесь в поддержку.")
        await state.clear()
        return
    
    await message.answer("⏳ Обрабатываю файл с банковскими выписками...")
    
    try:
        # Скачиваем файл
        file = await bot.get_file(document.file_id)
        file_path = os.path.join(tempfile.gettempdir(), document.file_name)
        await bot.download_file(file.file_path, file_path)
        
        # Обрабатываем файл
        success, message_text = await process_bank_statement(file_path, candidate_uuid)
        
        # Удаляем временный файл
        os.remove(file_path)
        
        if success:
            await message.answer(f"✅ {message_text}")
        else:
            await message.answer(f"❌ {message_text}")
        
        await state.clear()
        await cmd_docs(message, state)
    except Exception as e:
        logger.error(f"Error processing bank statement: {e}")
        await message.answer(
            "⚠️ Произошла ошибка при обработке файла. Убедитесь, что формат соответствует требованиям."
        )
        await state.clear()

@dp.message(AuthState.document_upload, F.document)
async def handle_document_upload(message: Message, state: FSMContext):
    chat_id = message.chat.id
    document = message.document
    data = await state.get_data()
    selected_doc = data.get('selected_doc')
    
    if not selected_doc:
        await message.answer("⚠️ Документ не выбран. Воспользуйтесь командой /docs")
        await state.clear()
        return
    
    candidate_uuid = await get_candidate_uuid_by_chat_id(chat_id)
    if not candidate_uuid:
        await message.answer("⚠️ Ваш профиль не найден. Обратитесь в поддержку.")
        await state.clear()
        return
    
    await message.answer("⏳ Загружаю документ...")
    
    try:
        minio_client = get_minio_client()
        # Получаем файл из Telegram
        file = await bot.get_file(document.file_id)
        file_bytes = await bot.download_file(file.file_path)
        
        # Конвертируем в bytes если это еще не bytes
        if isinstance(file_bytes, io.BytesIO):
            file_bytes = file_bytes.getvalue()
        
        # Генерируем уникальное имя файла
        file_extension = document.file_name.split('.')[-1] if document.file_name else 'bin'
        s3_key = f"{candidate_uuid}/{selected_doc['id']}.{file_extension}"
        bucket_name = "candidates"
        
        # Проверяем существует ли бакет, если нет - создаем
        if not minio_client.bucket_exists(bucket_name):
            minio_client.make_bucket(bucket_name)
        
        # Загружаем файл в MinIO
        minio_client.put_object(
            bucket_name,
            s3_key,
            io.BytesIO(file_bytes),  # Обертываем в BytesIO
            length=len(file_bytes),
            content_type=document.mime_type
        )
        
        # Сохраняем метаданные в базу данных
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    UPDATE hr.candidate_document
                    SET status_id = 2,
                        s3_bucket = %s,
                        s3_key = %s,
                        file_size = %s,
                        content_type = %s,
                        submitted_at = NOW(),
                        updated_at = NOW()
                    WHERE document_id = %s
                """, (
                    bucket_name,
                    s3_key,
                    document.file_size,
                    document.mime_type,
                    selected_doc['id']
                ))
                
                cursor.execute("""
                    INSERT INTO hr.document_history (document_uuid, status_id, created_at)
                    VALUES (%s, 2, NOW())
                """, (selected_doc['id'],))
                
                conn.commit()
        
        await message.answer("✅ Документ успешно загружен!")
        await state.clear()
        await cmd_docs(message, state)
        
    except Exception as e:
        logger.error(f"MinIO error: {e}")
        await message.answer("⚠️ Ошибка при сохранении документа в хранилище. Попробуйте позже.")
        await state.clear()
    except Exception as e:
        logger.error(f"Error uploading document: {e}")
        await message.answer("⚠️ Произошла ошибка при загрузке документа.")
        await state.clear()

@dp.message(Command("menu"))
async def cmd_menu(message: Message, state: FSMContext):
    await state.clear()  # Сбрасываем состояние
    chat_id = message.chat.id
    
    if not await is_user_authorized(chat_id):
        await message.answer(
            "🔐 Для доступа к системе сначала введите код приглашения "
            "через команду /start и примите политику конфиденциальности"
        )
        return
    
    # Создаем клавиатуру меню
    menu_kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📁 Мои документы")],
            [KeyboardButton(text="👤 Мой профиль")],
            [KeyboardButton(text="🆘 Поддержка")]
        ],
        resize_keyboard=True
    )
    
    await message.answer(
        "📋 Главное меню:",
        reply_markup=menu_kb
    )
    
    await save_message(chat_id, "Пользователь открыл меню", False)

@dp.message(F.text == "📁 Мои документы")
async def my_documents(message: Message, state: FSMContext):
    await cmd_docs(message, state)

@dp.message(F.text == "👤 Мой профиль")
async def my_profile(message: Message):
    chat_id = message.chat.id
    
    if not await is_user_authorized(chat_id):
        await message.answer(
            "🔐 Для доступа к системе сначала введите код приглашения "
            "через команду /start и примите политику конфиденциальности"
        )
        return
    
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT c.first_name, c.middle_name, c.last_name, c.email, s.name as status
                    FROM hr.candidate c
                    JOIN hr.candidate_status s ON c.status_id = s.status_id
                    WHERE c.telegram_chat_id = %s
                """, (chat_id,))
                
                result = cursor.fetchone()
                if not result:
                    await message.answer("⚠Ваш профиль не найден. Обратитесь в поддержку.")
            first_name, middle_name, last_name, email, status = result
            response = (
                f"👤 <b>Ваш профиль</b>\n\n"
                f"<b>ФИО:</b> {last_name} {first_name} {middle_name or ''}\n"
                f"<b>Email:</b> {email or 'не указан'}\n"
                f"<b>Статус:</b> {status}\n\n"
                "Используйте кнопки ниже для управления профилем."
            )
            
            profile_kb = ReplyKeyboardMarkup(
                keyboard=[
                    [KeyboardButton(text="✏️ Изменить данные")],
                    [KeyboardButton(text="↩️ Назад в меню")]
                ],
                resize_keyboard=True
            )
            
            await message.answer(response, reply_markup=profile_kb, parse_mode="HTML")
            await save_message(chat_id, "Пользователь просмотрел профиль", True)
                
    except Exception as e:
        logger.error(f"Error displaying profile: {e}")
        await message.answer(
            "⚠️ Произошла ошибка при получении данных профиля. Пожалуйста, попробуйте позже."
        )

@dp.message(F.text == "🆘 Поддержка")
async def support(message: Message):
    chat_id = message.chat.id

    if not await is_user_authorized(chat_id):
        await message.answer(
            "🔐 Для доступа к системе сначала введите код приглашения "
            "через команду /start и примите политику конфиденциальности"
        )
        return

    support_kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📞 Позвонить в поддержку")],
            [KeyboardButton(text="✉️ Написать сообщение")],
            [KeyboardButton(text="↩️ Назад в меню")]
        ],
        resize_keyboard=True
    )

    response = (
        "🆘 <b>Служба поддержки</b>\n\n"
        "Вы можете:\n"
        "- Позвонить нам: +7 (123) 456-78-90\n"
        "- Написать сообщение (ответьте на это сообщение)\n"
        "- Использовать команду /help для частых вопросов"
    )

    await message.answer(response, reply_markup=support_kb, parse_mode="HTML")
    await save_message(chat_id, "Пользователь обратился в поддержку", True)

@dp.message(F.text == "↩️ Назад в меню")
async def back_to_menu_handler(message: Message, state: FSMContext):
    await cmd_menu(message, state)

@dp.message(F.text == "✏️ Изменить данные")
async def edit_profile(message: Message, state: FSMContext):
    chat_id = message.chat.id
    if not await is_user_authorized(chat_id):
        await message.answer(
            "🔐 Для доступа к системе сначала введите код приглашения "
            "через команду /start и примите политику конфиденциальности"
        )
        return

    edit_kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="✏️ Изменить имя")],
            [KeyboardButton(text="✏️ Изменить email")],
            [KeyboardButton(text="↩️ Назад в профиль")]
        ],
        resize_keyboard=True
    )

    await message.answer(
        "✏️ <b>Редактирование профиля</b>\n\n"
        "Выберите, что хотите изменить:",
        reply_markup=edit_kb,
        parse_mode="HTML"
    )
    await save_message(chat_id, "Пользователь начал редактирование профиля", True)

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())