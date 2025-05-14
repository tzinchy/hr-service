import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message,
    ReplyKeyboardRemove,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
    Location,
    BufferedInputFile
)
from datetime import datetime
from candidate.database import get_connection, get_minio_client
from core.config import settings
from candidate.tg_service import (
    is_user_authorized,
    process_bank_statement,
    save_message,
    create_required_documents,
    get_candidate_uuid_by_chat_id,
    save_location
)
import os
import tempfile
import io

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Состояния FSM
class AuthState(StatesGroup):
    waiting_for_code = State()
    waiting_for_privacy_accept = State()
    document_upload = State()
    waiting_for_bank_data = State()
    waiting_for_location = State()
    editing_profile = State()
    document_action = State()

# Инициализация бота
bot = Bot(token=settings.bot.TELEGRAM_TOKEN)
dp = Dispatcher()

DOCUMENT_STATUSES = {
    1: "Не загружен ❌",
    2: "Заказан 🛒",
    3: "Ожидает проверки ⏳",
    4: "Проверен ✅",
    5: "Отправьте еще раз🔄"
}

# Вспомогательные функции
async def get_main_keyboard():
    """Возвращает клавиатуру главного меню"""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📁 Мои документы"), KeyboardButton(text="📍 Поделиться геолокацией")],
            [KeyboardButton(text="🗺️ Моя геолокация"), KeyboardButton(text="👤 Мой профиль")],
            [KeyboardButton(text="🆘 Поддержка")]
        ],
        resize_keyboard=True
    )

async def show_main_menu(message: Message, first_name: str = "", last_name: str = ""):
    """Показывает главное меню"""
    greeting = f"👋 Добро пожаловать, {first_name} {last_name}!\n" if first_name else ""
    await message.answer(
        f"{greeting}Выберите действие:",
        reply_markup=await get_main_keyboard()
    )
    await save_message(message.chat.id, "Пользователю показано главное меню", True)

async def update_document_status(document_id: int, new_status: int):
    """Обновляет статус документа"""
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    UPDATE hr.candidate_document
                    SET status_id = %s,
                        updated_at = NOW()
                    WHERE document_id = %s
                    RETURNING document_id, status_id
                """, (new_status, document_id))
                
                updated_doc = cursor.fetchone()
                
                if updated_doc:
                    cursor.execute("""
                        INSERT INTO hr.document_history (document_uuid, status_id, created_at)
                        VALUES (%s, %s, NOW())
                    """, (updated_doc[0], updated_doc[1]))
                    
                    conn.commit()
                    return True
        return False
    except Exception as e:
        logger.error(f"Error updating document status: {e}")
        return False

# Обработчики команд
@dp.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    """Обработчик команды /start"""
    await save_message(message.chat.id, f"Пользователь {message.from_user.full_name} запустил бота", False)
    await message.answer(
        "🔑 Для доступа к системе введите код приглашения, "
        "который вы получили по email:",
        reply_markup=ReplyKeyboardRemove()
    )
    await state.set_state(AuthState.waiting_for_code)

@dp.message(AuthState.waiting_for_code, F.text)
async def process_invitation_code(message: Message, state: FSMContext):
    """Обработка кода приглашения"""
    code = message.text.strip().upper()
    chat_id = message.chat.id
    await save_message(chat_id, f"Пользователь ввел код: {code}", False)

    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT candidate_uuid, first_name, last_name, agreement_accepted, status_id 
                    FROM hr.candidate 
                    WHERE invitation_code = %s
                    """,
                    (code,)
                )
                
                result = cursor.fetchone()
                
                if not result:
                    await message.answer("❌ Неверный код приглашения.")
                    return
                
                candidate_uuid, first_name, last_name, agreement_accepted, current_status = result
                
                cursor.execute(
                    """
                    UPDATE hr.candidate 
                    SET telegram_chat_id = %s
                    WHERE candidate_uuid = %s
                    """,
                    (chat_id, candidate_uuid)
                )
                
                if current_status == 2:
                    cursor.execute(
                        """
                        UPDATE hr.candidate
                        SET status_id = 3,
                            registered_at = NOW()
                        WHERE candidate_uuid = %s
                        """,
                        (candidate_uuid,)
                    )
                
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
                    await create_required_documents(candidate_uuid)
                    await show_main_menu(message, first_name, last_name)
                    await state.clear()
                else:
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
                        "📄 Пожалуйста, ознакомьтесь с нашей Политикой конфиденциальности...",
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
        await message.answer("⚠️ Произошла ошибка.")

@dp.callback_query(AuthState.waiting_for_privacy_accept, F.data == "privacy_accept")
async def accept_privacy(callback: types.CallbackQuery, state: FSMContext):
    """Обработка принятия политики конфиденциальности"""
    chat_id = callback.message.chat.id
    data = await state.get_data()
    candidate_uuid = data['candidate_uuid']
    
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
                
                await create_required_documents(candidate_uuid)
                conn.commit()
                
                await callback.message.edit_text(
                    f"✅ Спасибо, {first_name}! Вы приняли условия политики конфиденциальности."
                )
                
                await save_message(
                    chat_id,
                    f"Пользователь {first_name} {last_name} принял политику конфиденциальности",
                    True
                )
                
                await show_main_menu(callback.message, first_name, last_name)
                await state.clear()
                
    except Exception as e:
        logger.error(f"Error during privacy acceptance: {e}")
        await callback.message.answer("⚠️ Произошла ошибка при сохранении.")

@dp.callback_query(AuthState.waiting_for_privacy_accept, F.data == "privacy_decline")
async def decline_privacy(callback: types.CallbackQuery, state: FSMContext):
    """Обработка отказа от политики конфиденциальности"""
    await callback.message.edit_text(
        "❌ Вы отказались от принятия политики конфиденциальности. "
        "Для использования бота необходимо принять условия."
    )
    await state.clear()
    await save_message(callback.message.chat.id, "Пользователь отказался от политики конфиденциальности", True)

# Обработчики документов
@dp.message(Command("docs"))
@dp.message(F.text == "📁 Мои документы")
async def cmd_docs(message: Message, state: FSMContext):
    """Обработчик команды /docs и кнопки документов"""
    chat_id = message.chat.id
    await save_message(chat_id, "Пользователь запросил документы", False)
    
    if not await is_user_authorized(chat_id):
        await message.answer("🔐 Для доступа к системе сначала авторизуйтесь.")
        return
    
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT c.candidate_uuid, c.first_name, c.last_name 
                    FROM hr.candidate c
                    WHERE c.telegram_chat_id = %s
                """, (chat_id,))
                
                candidate = cursor.fetchone()
                if not candidate:
                    await message.answer("⚠️ Ваш профиль не найден.")
                    return
                
                candidate_uuid, first_name, last_name = candidate
                
                cursor.execute("""
                    SELECT d.document_id, t.name, d.status_id, t.template_id
                    FROM hr.candidate_document d
                    JOIN hr.document_template t ON d.template_id = t.template_id
                    WHERE d.candidate_id = %s
                    ORDER BY t.order_position
                """, (candidate_uuid,))
                
                documents = cursor.fetchall()
                
                if not documents:
                    await create_required_documents(candidate_uuid)
                    cursor.execute("""
                        SELECT d.document_id, t.name, d.status_id, t.template_id
                        FROM hr.candidate_document d
                        JOIN hr.document_template t ON d.template_id = t.template_id
                        WHERE d.candidate_id = %s
                        ORDER BY t.order_position
                    """, (candidate_uuid,))
                    documents = cursor.fetchall()
                
                keyboard = []
                for doc in documents:
                    doc_id, doc_name, status_id, template_id = doc
                    status = DOCUMENT_STATUSES[status_id]
                    keyboard.append([KeyboardButton(text=f"{doc_name} {status}")])
                
                keyboard.append([KeyboardButton(text="↩️ Назад в меню")])
                
                doc_kb = ReplyKeyboardMarkup(
                    keyboard=keyboard,
                    resize_keyboard=True
                )
                
                docs_info = {doc[1]: {"id": doc[0], "template_id": doc[3], "status_id": doc[2]} for doc in documents}
                await state.update_data(docs_info=docs_info)
                
                response = f"📂 {first_name}, выберите документ для загрузки или изменения статуса:\n\n"
                for doc in documents:
                    doc_id, doc_name, status_id, _ = doc
                    status = DOCUMENT_STATUSES[status_id]
                    response += f"{doc_name}: {status}\n"
                
                await message.answer(response, reply_markup=doc_kb)
                await save_message(chat_id, "Пользователю отображен список документов", True)
    except Exception as e:
        logger.error(f"Error displaying documents: {e}")
        await message.answer("⚠️ Произошла ошибка при получении документов.")

@dp.message(
    lambda message: message.text and any(
        doc_name in message.text 
        for doc_name in [
            "Excel с открытыми счетами", "Справка о судимости", "Полис ОМС", "СНИЛС", 
            "Трудовая книжка", "Паспорт", "Свидетельство о браке/разводе", 
            "Военный билет/приписное", "ИНН", "2-НДФЛ", "Справка из наркодиспансера",
            "Справка из психодиспансера", "Общая медицинская справка", 
            "Социальные сети", "Дополнительные документы"
        ]
    )
)
async def handle_document_selection(message: Message, state: FSMContext):
    """Обработка выбора документа"""
    chat_id = message.chat.id
    
    if not await is_user_authorized(chat_id):
        await message.answer("🔐 Для доступа к системе сначала авторизуйтесь.")
        return
    
    data = await state.get_data()
    docs_info = data.get('docs_info', {})
    
    # Находим полное имя документа из сообщения
    doc_name = next((name for name in docs_info.keys() if name in message.text), None)
    
    if not doc_name:
        await message.answer("Выберите документ из списка или используйте команду /docs")
        return
    
    doc_info = docs_info[doc_name]
    
    # Создаем клавиатуру для выбора действия с документом
    buttons = []
    
    # Всегда показываем кнопку загрузки
    buttons.append([KeyboardButton(text="📤 Загрузить документ")])
    
    # Показываем кнопку "Заказан" только если статус "Не загружен"
    if doc_info["status_id"] == 1:
        buttons.append([KeyboardButton(text="🛒 Отметить как заказанный")])
    
    # Показываем кнопку скачивания если документ загружен
    if doc_info["status_id"] in [3, 4, 5]:
        buttons.append([KeyboardButton(text="⬇️ Скачать документ")])
    
    buttons.append([KeyboardButton(text="↩️ Назад к документам")])
    
    action_kb = ReplyKeyboardMarkup(
        keyboard=buttons,
        resize_keyboard=True
    )
    
    await message.answer(
        f"📄 Документ: <b>{doc_name}</b>\n"
        f"Статус: <b>{DOCUMENT_STATUSES[doc_info['status_id']]}</b>\n\n"
        f"Выберите действие:",
        reply_markup=action_kb,
        parse_mode="HTML"
    )
    
    await state.set_state(AuthState.document_action)
    await state.update_data(selected_doc=doc_info, doc_name=doc_name)

@dp.message(AuthState.document_action, F.text == "📤 Загрузить документ")
async def request_document_upload(message: Message, state: FSMContext):
    """Запрос на загрузку документа"""
    data = await state.get_data()
    doc_name = data.get('doc_name')
    
    if doc_name == "Excel с открытыми счетами":
        await message.answer(
            "📊 Пожалуйста, загрузите Excel файл с выписками банка."
        )
        await state.set_state(AuthState.waiting_for_bank_data)
        return
    
    await message.answer(f"📄 Пожалуйста, загрузите файл для документа: {doc_name}")
    await state.set_state(AuthState.document_upload)

@dp.message(AuthState.document_action, F.text == "🛒 Отметить как заказанный")
async def mark_as_ordered(message: Message, state: FSMContext):
    """Отметить документ как заказанный"""
    data = await state.get_data()
    selected_doc = data.get('selected_doc')
    doc_name = data.get('doc_name')
    
    if not selected_doc:
        await message.answer("⚠️ Документ не выбран.")
        await state.clear()
        return
    
    if await update_document_status(selected_doc['id'], 2):
        await message.answer(f"✅ Документ '{doc_name}' отмечен как заказанный!")
        await cmd_docs(message, state)
    else:
        await message.answer("⚠️ Произошла ошибка при изменении статуса документа.")

@dp.message(AuthState.document_action, F.text == "⬇️ Скачать документ")
async def download_document(message: Message, state: FSMContext):
    """Скачивание документа"""
    data = await state.get_data()
    selected_doc = data.get('selected_doc')
    doc_name = data.get('doc_name')
    
    if not selected_doc:
        await message.answer("⚠️ Документ не выбран.")
        await state.clear()
        return
    
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT s3_bucket, s3_key, content_type
                    FROM hr.candidate_document
                    WHERE document_id = %s
                """, (selected_doc['id'],))
                
                doc_data = cursor.fetchone()
                
                if not doc_data or not doc_data[0] or not doc_data[1]:
                    await message.answer("⚠️ Файл документа не найден.")
                    return
                
                bucket, key, content_type = doc_data
                minio_client = get_minio_client()
                
                try:
                    file_data = minio_client.get_object(bucket, key)
                    file_bytes = file_data.read()
                    
                    # Определяем расширение файла
                    extension = "bin"
                    if content_type:
                        if "pdf" in content_type:
                            extension = "pdf"
                        elif "image" in content_type:
                            extension = content_type.split("/")[-1]
                        elif "excel" in content_type or "spreadsheet" in content_type:
                            extension = "xlsx"
                        elif "word" in content_type:
                            extension = "docx"
                    
                    file_name = f"{doc_name.replace(' ', '_')}.{extension}"
                    
                    # Отправляем файл пользователю
                    await message.answer_document(
                        BufferedInputFile(
                            file_bytes,
                            filename=file_name
                        ),
                        caption=f"📄 {doc_name}"
                    )
                    
                    await save_message(
                        message.chat.id,
                        f"Пользователь скачал документ: {doc_name}",
                        True
                    )
                    
                except Exception as e:
                    logger.error(f"Error downloading file from MinIO: {e}")
                    await message.answer("⚠️ Ошибка при получении файла из хранилища.")
                
                finally:
                    if 'file_data' in locals():
                        file_data.close()
                        file_data.release_conn()
    
    except Exception as e:
        logger.error(f"Error in download_document: {e}")
        await message.answer("⚠️ Произошла ошибка при подготовке документа.")

@dp.message(AuthState.document_action, F.text == "↩️ Назад к документам")
async def back_to_documents(message: Message, state: FSMContext):
    """Возврат к списку документов"""
    await state.clear()
    await cmd_docs(message, state)

@dp.message(AuthState.waiting_for_bank_data, F.document)
async def handle_bank_statement(message: Message, state: FSMContext):
    """Обработка выписки банка"""
    chat_id = message.chat.id
    document = message.document
    
    if not document.file_name.endswith(('.xlsx', '.xls')):
        await message.answer("❌ Пожалуйста, загрузите файл Excel (.xlsx или .xls)")
        return
    
    candidate_uuid = await get_candidate_uuid_by_chat_id(chat_id)
    if not candidate_uuid:
        await message.answer("⚠️ Ваш профиль не найден.")
        await state.clear()
        return
    
    await message.answer("⏳ Обрабатываю файл с банковскими выписками...")
    
    try:
        file = await bot.get_file(document.file_id)
        file_path = os.path.join(tempfile.gettempdir(), document.file_name)
        await bot.download_file(file.file_path, file_path)
        
        success, message_text = await process_bank_statement(file_path, candidate_uuid)
        os.remove(file_path)
        
        if success:
            await message.answer(f"✅ {message_text}")
        else:
            await message.answer(f"❌ {message_text}")
        
        await state.clear()
        await cmd_docs(message, state)
    except Exception as e:
        logger.error(f"Error processing bank statement: {e}")
        await message.answer("⚠️ Произошла ошибка при обработке файла.")
        await state.clear()

@dp.message(AuthState.document_upload, F.document)
async def handle_document_upload(message: Message, state: FSMContext):
    """Обработка загрузки документа"""
    chat_id = message.chat.id
    document = message.document
    data = await state.get_data()
    selected_doc = data.get('selected_doc')
    
    if not selected_doc:
        await message.answer("⚠️ Документ не выбран.")
        await state.clear()
        return
    
    candidate_uuid = await get_candidate_uuid_by_chat_id(chat_id)
    if not candidate_uuid:
        await message.answer("⚠️ Ваш профиль не найден.")
        await state.clear()
        return
    
    await message.answer("⏳ Загружаю документ...")
    
    try:
        minio_client = get_minio_client()
        file = await bot.get_file(document.file_id)
        file_bytes = await bot.download_file(file.file_path)
        
        if isinstance(file_bytes, io.BytesIO):
            file_bytes = file_bytes.getvalue()
        
        file_extension = document.file_name.split('.')[-1] if document.file_name else 'bin'
        s3_key = f"{candidate_uuid}/{selected_doc['id']}.{file_extension}"
        bucket_name = "candidates"
        
        if not minio_client.bucket_exists(bucket_name):
            minio_client.make_bucket(bucket_name)
        
        minio_client.put_object(
            bucket_name,
            s3_key,
            io.BytesIO(file_bytes),
            length=len(file_bytes),
            content_type=document.mime_type
        )
        
        if await update_document_status(selected_doc['id'], 3):
            await message.answer("✅ Документ успешно загружен!")
            await state.clear()
            await cmd_docs(message, state)
        else:
            await message.answer("⚠️ Документ загружен, но не удалось обновить статус.")
        
    except Exception as e:
        logger.error(f"Error uploading document: {e}")
        await message.answer("⚠️ Произошла ошибка при загрузке документа.")
        await state.clear()

# Остальные обработчики (геолокация, профиль, поддержка и т.д.)
@dp.message(F.text == "📍 Поделиться геолокацией")
async def request_location(message: Message, state: FSMContext):
    """Запрашивает геолокацию у пользователя"""
    location_kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📍 Отправить мою геолокацию", request_location=True)],
            [KeyboardButton(text="↩️ Назад")]
        ],
        resize_keyboard=True
    )
    
    await message.answer(
        "Пожалуйста, поделитесь вашей текущей геолокацией:",
        reply_markup=location_kb
    )
    await state.set_state(AuthState.waiting_for_location)
    await save_message(message.chat.id, "Пользователь запросил отправку геолокации", False)

@dp.message(AuthState.waiting_for_location, F.location)
async def handle_location(message: Message, state: FSMContext):
    """Обрабатывает полученную геолокацию"""
    location = message.location
    chat_id = message.chat.id
    
    try:
        candidate_uuid = await get_candidate_uuid_by_chat_id(chat_id)
        if not candidate_uuid:
            await message.answer("⚠️ Ваш профиль не найден.")
            await state.clear()
            return
        
        success = await save_location(
            candidate_uuid=candidate_uuid,
            latitude=location.latitude,
            longitude=location.longitude,
            accuracy=location.horizontal_accuracy
        )
        
        if success:
            await message.answer(
                "✅ Ваша геолокация успешно сохранена!",
                reply_markup=await get_main_keyboard()
            )
            await save_message(
                chat_id,
                f"Пользователь отправил геолокацию: {location.latitude}, {location.longitude}",
                True
            )
        else:
            await message.answer(
                "⚠️ Не удалось сохранить вашу геолокацию.",
                reply_markup=await get_main_keyboard()
            )
        
        await state.clear()
        
    except Exception as e:
        logger.error(f"Error handling location: {e}")
        await message.answer(
            "⚠️ Произошла ошибка при обработке вашей геолокации.",
            reply_markup=await get_main_keyboard()
        )
        await state.clear()

@dp.message(F.text == "🗺️ Моя геолокация")
async def show_my_location(message: Message):
    """Показывает сохраненную геолокацию пользователя"""
    chat_id = message.chat.id
    
    try:
        candidate_uuid = await get_candidate_uuid_by_chat_id(chat_id)
        if not candidate_uuid:
            await message.answer("⚠️ Ваш профиль не найден.")
            return
        
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT latitude, longitude, accuracy, created_at
                    FROM hr.candidate_location
                    WHERE candidate_uuid = %s
                    ORDER BY created_at DESC
                    LIMIT 1
                """, (candidate_uuid,))
                
                location = cursor.fetchone()
                
                if not location:
                    await message.answer("Вы еще не отправляли свою геолокацию.")
                    return
                
                lat, lon, acc, created_at = location
                created_str = created_at.strftime("%d.%m.%Y %H:%M")
                
                response = (
                    "🗺️ <b>Ваша сохраненная геолокация</b>\n\n"
                    f"<b>Широта:</b> {lat}\n"
                    f"<b>Долгота:</b> {lon}\n"
                    f"<b>Точность:</b> {acc if acc else 'не указана'} м\n"
                    f"<b>Обновлено:</b> {created_str}"
                )
                
                await message.answer(response, parse_mode="HTML")
                await save_message(chat_id, "Пользователь запросил сохраненную геолокацию", True)
                
    except Exception as e:
        logger.error(f"Error fetching location: {e}")
        await message.answer("⚠️ Ошибка при получении геолокации.")

@dp.message(F.text == "👤 Мой профиль")
async def my_profile(message: Message):
    """Показывает профиль пользователя"""
    chat_id = message.chat.id
    
    if not await is_user_authorized(chat_id):
        await message.answer("🔐 Для доступа к системе сначала авторизуйтесь.")
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
                    await message.answer("⚠️ Ваш профиль не найден.")
                    return
                
                first_name, middle_name, last_name, email, status = result
                response = (
                    "👤 <b>Ваш профиль</b>\n\n"
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
        await message.answer("⚠️ Ошибка при получении данных профиля.")

@dp.message(F.text == "🆘 Поддержка")
async def support(message: Message):
    """Обработчик кнопки поддержки"""
    chat_id = message.chat.id
    await save_message(chat_id, "Пользователь обратился в поддержку", False)
    
    support_kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="✉️ Написать сообщение")],
            [KeyboardButton(text="↩️ Назад в меню")]
        ],
        resize_keyboard=True
    )

    response = (
        "🆘 <b>Служба поддержки</b>\n\n"
        "Вы можете:\n"
        "- Написать сообщение (Просто напишите в чат!;))\n"
        "- Использовать команду /help для частых вопросов"
    )

    await message.answer(response, reply_markup=support_kb, parse_mode="HTML")
    await save_message(chat_id, "Показано меню поддержки", True)

@dp.message(F.text == "↩️ Назад в меню")
async def back_to_menu(message: Message, state: FSMContext):
    """Возврат в главное меню"""
    await state.clear()
    await show_main_menu(message)
    await save_message(message.chat.id, "Пользователь вернулся в меню", False)

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())