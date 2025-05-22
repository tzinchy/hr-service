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
    BufferedInputFile
)
from datetime import datetime
from repository.database import get_connection, get_minio_client
from core.config import settings
import os
import tempfile
import io
from service.bot_service import get_status_text, is_excel_file
from repository.bot_repositoty import update_document_status, save_location, save_message, create_required_documents, is_user_authorized, get_candidate_uuid_by_chat_id
from urllib.parse import quote
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def generate_doc_link(doc_name: str, base_url: str = "http://80.74.24.255:8502") -> str:
    """
    Генерирует корректную URL-ссылку для документа
    
    Параметры:
    - doc_name: название документа (например, "Паспорт (разворот с фото)")
    - base_url: базовый URL приложения
    
    Возвращает:
    - Готовую ссылку с правильно закодированным параметром
    """
    # Заменяем пробелы на обычные пробелы (не на _) и кодируем один раз
    encoded_name = quote(doc_name)
    return f"{base_url.rstrip('/')}/?doc={encoded_name}"

class AuthState(StatesGroup):
    waiting_for_code = State()
    waiting_for_privacy_accept = State()
    document_upload = State()
    waiting_for_bank_data = State()
    waiting_for_location = State()
    editing_profile = State()
    document_action = State()
    waiting_for_support_message = State()  

# Инициализация бота
bot = Bot(token=settings.bot.TELEGRAM_TOKEN)
dp = Dispatcher()

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

# Обработчики команд
@dp.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    """Обработчик команды /start"""
    await save_message(message.chat.id, message.text, False)  # Сохраняем исходное сообщение
    await save_message(message.chat.id, f"Пользователь {message.from_user.full_name} запустил бота", True)
    
    await message.answer(
        "🔑 Для доступа к системе введите код приглашения, "
        "который вы получили по email:",
        reply_markup=ReplyKeyboardRemove()
    )
    await state.set_state(AuthState.waiting_for_code)

@dp.message(AuthState.waiting_for_code, F.text)
async def process_invitation_code(message: Message, state: FSMContext):
    """Обработка кода приглашения"""
    await save_message(message.chat.id, message.text, False)  # Сохраняем введенный код
    
    code = message.text.strip().upper()
    chat_id = message.chat.id
    await save_message(chat_id, f"Пользователь ввел код: {code}", True)

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

# Обработчики документов с callback-кнопками
@dp.message(Command("docs"))
@dp.message(F.text == "📁 Мои документы")
async def cmd_docs(message: Message, state: FSMContext):
    """Обработчик команды /docs и кнопки документов"""
    await save_message(message.chat.id, message.text, False)
    chat_id = message.chat.id
    await save_message(chat_id, "Пользователь запросил документы", True)
    
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
                
                # Создаем инлайн-клавиатуру с callback-кнопками
                keyboard = []
                for doc in documents:
                    doc_id, doc_name, status_id, _ = doc
                    status_text = get_status_text(status_id)
                    keyboard.append([
                        InlineKeyboardButton(
                            text=f"{doc_name} - {status_text}",
                            callback_data=f"doc_{doc_id}"
                        )
                    ])
                
                keyboard.append([InlineKeyboardButton(
                    text="↩️ Назад в меню",
                    callback_data="back_to_menu"
                )])
                
                docs_kb = InlineKeyboardMarkup(inline_keyboard=keyboard)
                
                docs_info = {doc[1]: {"id": doc[0], "template_id": doc[3], "status_id": doc[2]} for doc in documents}
                await state.update_data(docs_info=docs_info)
                
                response = f"📂 {first_name}, ваши документы:\n\n"
                await message.answer(response, reply_markup=docs_kb)
                await save_message(chat_id, "Пользователю отображен список документов", True)
    except Exception as e:
        logger.error(f"Error displaying documents: {e}")
        await message.answer("⚠️ Произошла ошибка при получении документов.")

@dp.callback_query(F.data.startswith("doc_"))
async def handle_document_callback(callback: types.CallbackQuery, state: FSMContext):
    """Обработка выбора документа через callback"""
    document_id = callback.data.split("_")[1]
    chat_id = callback.message.chat.id
    
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT t.name, d.status_id, d.template_id
                    FROM hr.candidate_document d
                    JOIN hr.document_template t ON d.template_id = t.template_id
                    WHERE d.document_id = %s
                """, (document_id,))
                
                doc_info = cursor.fetchone()
                if not doc_info:
                    await callback.answer("Документ не найден")
                    return
                
                doc_name, status_id, template_id = doc_info
                                # Формируем ссылку
                doc_link = generate_doc_link(doc_name)
                # Создаем клавиатуру с действиями для документа
                keyboard = []
                
                # Для статусов "Не загружен", "Заказан" и "Требуется новый вариант" показываем кнопку загрузки
                if status_id in [1, 2, 5]:
                    keyboard.append([InlineKeyboardButton(
                        text="📤 Загрузить документ", 
                        callback_data=f"upload_{document_id}"
                    )])
                
                # Для статуса "Не загружен" показываем кнопку "Заказан"
                if status_id == 1:
                    keyboard.append([InlineKeyboardButton(
                        text="🛒 Отметить как заказанный", 
                        callback_data=f"order_{document_id}"
                    )])
                
                # Для статусов "Ожидает проверки" и "Проверен" показываем кнопку скачивания
                if status_id in [3, 4]:
                    keyboard.append([InlineKeyboardButton(
                        text="⬇️ Скачать документ", 
                        callback_data=f"download_{document_id}"
                    )])
                
                # Для статуса "Проверен" показываем кнопку запроса новой загрузки
                if status_id == 4:
                    keyboard.append([InlineKeyboardButton(
                        text="🔄 Запросить новый вариант", 
                        callback_data=f"request_reupload_{document_id}"
                    )])
                
                keyboard.append([InlineKeyboardButton(
                    text="↩️ Назад к документам", 
                    callback_data="back_to_docs"
                )])
                
                reply_markup = InlineKeyboardMarkup(inline_keyboard=keyboard)
                
                await callback.message.edit_text(
                    f"📄 Документ: <b>{doc_name}</b>\n"
                    f"Статус: <b>{get_status_text(status_id)}</b>\n\n"
                    f"🔗 Инструкция: {doc_link}\n\n"
                    f"Выберите действие:",
                    reply_markup=reply_markup,
                    parse_mode="HTML"
                )
                
                await state.set_state(AuthState.document_action)
                await state.update_data(selected_doc={
                    "id": document_id,
                    "template_id": template_id,
                    "status_id": status_id
                }, doc_name=doc_name)
                
                await callback.answer()
                
    except Exception as e:
        logger.error(f"Error handling document callback: {e}")
        await callback.answer("⚠️ Произошла ошибка")

@dp.callback_query(AuthState.document_action, F.data.startswith("upload_"))
async def handle_upload_callback(callback: types.CallbackQuery, state: FSMContext):
    """Обработка загрузки документа"""
    data = await state.get_data()
    doc_name = data.get('doc_name')
    
    await callback.message.edit_reply_markup()  # Убираем кнопки
    
    if doc_name == "Excel с открытыми счетами":
        await callback.message.answer("📊 Пожалуйста, загрузите Excel файл (.xlsx или .xls) с выписками банка.")
        await state.set_state(AuthState.waiting_for_bank_data)
    else:
        await callback.message.answer(f"📄 Пожалуйста, загрузите файл для документа: {doc_name}")
        await state.set_state(AuthState.document_upload)
    
    await callback.answer()

@dp.callback_query(AuthState.document_action, F.data.startswith("order_"))
async def handle_order_callback(callback: types.CallbackQuery, state: FSMContext):
    """Обработка отметки документа как заказанного"""
    document_id = callback.data.split("_")[1]
    data = await state.get_data()
    doc_name = data.get('doc_name')
    
    if await update_document_status(document_id, 2, callback.message.chat.id, doc_name):
        await callback.message.edit_text(
            f"✅ Документ '{doc_name}' отмечен как заказанный!",
            reply_markup=None
        )
        await cmd_docs(callback.message, state)
    else:
        await callback.message.answer("⚠️ Произошла ошибка при изменении статуса документа.")
    
    await callback.answer()

@dp.callback_query(AuthState.document_action, F.data.startswith("download_"))
async def handle_download_callback(callback: types.CallbackQuery, state: FSMContext):
    """Обработка скачивания документа"""
    document_id = callback.data.split("_")[1]
    data = await state.get_data()
    doc_name = data.get('doc_name')
    
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT s3_bucket, s3_key, content_type
                    FROM hr.candidate_document
                    WHERE document_id = %s
                """, (document_id,))
                
                doc_data = cursor.fetchone()
                
                if not doc_data or not doc_data[0] or not doc_data[1]:
                    await callback.message.answer("⚠️ Файл документа не найден.")
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
                    await callback.message.answer_document(
                        BufferedInputFile(
                            file_bytes,
                            filename=file_name
                        ),
                        caption=f"📄 {doc_name}"
                    )
                    
                    await save_message(
                        callback.message.chat.id,
                        f"Пользователь скачал документ: {doc_name}",
                        True
                    )
                    
                except Exception as e:
                    logger.error(f"Error downloading file from MinIO: {e}")
                    await callback.message.answer("⚠️ Ошибка при получении файла из хранилища.")
                
                finally:
                    if 'file_data' in locals():
                        file_data.close()
                        file_data.release_conn()
    
    except Exception as e:
        logger.error(f"Error in download_document: {e}")
        await callback.message.answer("⚠️ Произошла ошибка при подготовке документа.")
    
    await callback.answer()

@dp.callback_query(AuthState.document_action, F.data.startswith("request_reupload_"))
async def handle_request_reupload_callback(callback: types.CallbackQuery, state: FSMContext):
    """Обработка запроса новой загрузки документа"""
    document_id = callback.data.split("_")[2]
    data = await state.get_data()
    doc_name = data.get('doc_name')
    
    if await update_document_status(document_id, 5, callback.message.chat.id, doc_name):
        await callback.message.edit_text(
            f"🔄 Для документа '{doc_name}' запрошена повторная загрузка",
            reply_markup=None
        )
        
        # Предлагаем загрузить новый вариант
        reply_markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="📤 Загрузить новый вариант", 
                callback_data=f"upload_{document_id}"
            )]
        ])
        
        await callback.message.answer(
            f"Пожалуйста, загрузите новый вариант документа '{doc_name}':",
            reply_markup=reply_markup
        )
    else:
        await callback.message.answer("⚠️ Не удалось запросить повторную загрузку.")
    
    await callback.answer()

@dp.callback_query(F.data == "back_to_docs")
async def handle_back_to_docs(callback: types.CallbackQuery, state: FSMContext):
    """Обработка возврата к списку документов"""
    await state.clear()
    await callback.message.delete()  # Удаляем сообщение с кнопками
    await cmd_docs(callback.message, state)
    await callback.answer()

@dp.callback_query(F.data == "back_to_menu")
async def handle_back_to_menu(callback: types.CallbackQuery, state: FSMContext):
    """Обработка возврата в главное меню"""
    await state.clear()
    await callback.message.delete()
    await show_main_menu(callback.message)
    await callback.answer()

@dp.message(AuthState.waiting_for_bank_data, F.document)
async def handle_bank_statement(message: Message, state: FSMContext):
    """Обработка выписки банка"""
    await save_message(message.chat.id, "Пользователь загрузил файл", False)
    document = message.document
    
    if not is_excel_file(document.file_name):
        await message.answer("❌ Пожалуйста, загрузите файл Excel (.xlsx или .xls)")
        return
    
    data = await state.get_data()
    selected_doc = data.get('selected_doc')
    doc_name = data.get('doc_name')
    chat_id = message.chat.id
    
    if not selected_doc:
        await message.answer("⚠️ Документ не выбран.")
        await state.clear()
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
        
        # Проверка, что файл действительно Excel
        if not is_excel_file(file_path):
            await message.answer("❌ Загруженный файл не является Excel документом.")
            os.remove(file_path)
            return
        
        # Обработка файла
        minio_client = get_minio_client()
        with open(file_path, 'rb') as file_obj:
            file_bytes = file_obj.read()
        
        file_extension = document.file_name.split('.')[-1] if document.file_name else 'xlsx'
        s3_key = f"{candidate_uuid}/{selected_doc['id']}.{file_extension}"
        bucket_name = "candidates"
        
        if not minio_client.bucket_exists(bucket_name):
            minio_client.make_bucket(bucket_name)
        
        minio_client.put_object(
            bucket_name,
            s3_key,
            io.BytesIO(file_bytes),
            length=len(file_bytes),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        
        if await update_document_status(selected_doc['id'], 3, chat_id, doc_name):
            await message.answer(f"✅ Файл '{doc_name}' успешно загружен и отправлен на проверку!")
            await state.clear()
            await cmd_docs(message, state)
        else:
            await message.answer("⚠️ Файл загружен, но не удалось обновить статус.")
        
        os.remove(file_path)
    except Exception as e:
        logger.error(f"Error processing bank statement: {e}")
        await message.answer("⚠️ Произошла ошибка при обработке файла.")
        if 'file_path' in locals() and os.path.exists(file_path):
            os.remove(file_path)
        await state.clear()

@dp.message(AuthState.document_upload, F.document)
async def handle_document_upload(message: Message, state: FSMContext):
    """Обработка загрузки документа"""
    await save_message(message.chat.id, "Пользователь загрузил файл", False)
    chat_id = message.chat.id
    document = message.document
    data = await state.get_data()
    selected_doc = data.get('selected_doc')
    doc_name = data.get('doc_name')
    
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
        
        if await update_document_status(selected_doc['id'], 3, chat_id, doc_name):
            await message.answer(f"✅ Документ '{doc_name}' успешно загружен и отправлен на проверку!")
            await state.clear()
            await cmd_docs(message, state)
        else:
            await message.answer("⚠️ Документ загружен, но не удалось обновить статус.")
        
    except Exception as e:
        logger.error(f"Error uploading document: {e}")
        await message.answer("⚠️ Произошла ошибка при загрузке документа.")
        await state.clear()

# Остальные обработчики
@dp.message(F.text == "📍 Поделиться геолокацией")
async def request_location(message: Message, state: FSMContext):
    """Запрашивает геолокацию у пользователя"""
    await save_message(message.chat.id, message.text, False)
    location_kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📍 Отправить мою геолокацию", request_location=True)],
            [KeyboardButton(text="↩️ Назад в меню")]
        ],
        resize_keyboard=True
    )
    
    await message.answer(
        "Пожалуйста, поделитесь вашей текущей геолокацией:",
        reply_markup=location_kb
    )
    await state.set_state(AuthState.waiting_for_location)
    await save_message(message.chat.id, "Пользователь запросил отправку геолокации", True)

@dp.message(AuthState.waiting_for_location, F.location)
async def handle_location(message: Message, state: FSMContext):
    """Обрабатывает полученную геолокацию"""
    await save_message(message.chat.id, "Пользователь отправил геолокацию", False)
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
    await save_message(message.chat.id, message.text, False)
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
    await save_message(message.chat.id, message.text, False)
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
    await save_message(message.chat.id, message.text, False)
    chat_id = message.chat.id
    await save_message(chat_id, "Пользователь обратился в поддержку", True)
    
    support_kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="✉️ Написать")],  # Укороченный текст
            [KeyboardButton(text="↩️ Назад в меню")]
        ],
        resize_keyboard=True
    )

    response = (
        "🆘 <b>Служба поддержки</b>\n\n"
        "Вы можете:\n"
        "- Написать сообщение (кнопка '✉️ Написать')\n"
    )

    await message.answer(response, reply_markup=support_kb, parse_mode="HTML")
    await save_message(chat_id, "Показано меню поддержки", True)

@dp.message(F.text == "✉️ Написать")
async def start_support_message(message: Message, state: FSMContext):
    """Обработчик кнопки начала написания сообщения"""
    await save_message(message.chat.id, message.text, False)
    await message.answer("Пожалуйста, напишите ваше сообщение для поддержки:", reply_markup=ReplyKeyboardRemove())
    await state.set_state(AuthState.waiting_for_support_message)
    await save_message(message.chat.id, "Пользователь начал писать сообщение в поддержку", True)

@dp.message(AuthState.waiting_for_support_message)
async def handle_support_message(message: Message, state: FSMContext):
    """Обработка сообщения для поддержки"""
    await save_message(message.chat.id, message.text, False)
    # Здесь можно добавить логику отправки сообщения в поддержку
    # Например, сохранение в БД или пересылку администратору
    
    await message.answer("✅ Ваше сообщение отправлено в поддержку. Мы ответим вам в ближайшее время.", 
                        reply_markup=await get_main_keyboard())
    await state.clear()
    await save_message(message.chat.id, f"Пользователь отправил сообщение в поддержку: {message.text}", True)

@dp.message(F.text == "↩️ Назад в меню")
async def back_to_menu(message: Message, state: FSMContext):
    """Возврат в главное меню"""
    await save_message(message.chat.id, message.text, False)
    await state.clear()
    await show_main_menu(message)
    await save_message(message.chat.id, "Пользователь вернулся в меню", True)

@dp.message()
async def handle_unprocessed_messages(message: Message, state: FSMContext):
    """Обработчик непредусмотренных сообщений"""
    await save_message(message.chat.id, message.text, False)
    current_state = await state.get_state()
    logger.warning(f"Unhandled message: {message.text}. Current state: {current_state}")
    await message.answer("Извините, я не понял вашего сообщения. Пожалуйста, используйте кнопки меню.")

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())