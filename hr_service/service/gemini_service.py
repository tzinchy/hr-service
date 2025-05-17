from core.config import EXPERT_PROMPT, GEMINI_API_KEY
import logging
import google.generativeai as genai

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-2.0-flash-exp")


def generate_expert_response(prompt: str, chat_history: list) -> str:
    """
    Генерирует экспертный ответ на основе истории чата
    """
    try:
        # Формируем контекст из истории сообщений
        context = EXPERT_PROMPT + "\n\nКонтекст беседы:\n"
        for msg in chat_history[-5:]:  # Берем последние 5 сообщений для контекста
            role = "HR" if msg[2] else "Кандидат"
            context += f"{role}: {msg[0]}\n"

        full_prompt = f"{context}\nЭкспертный ответ HR на последнее сообщение кандидата:\n{prompt}"

        response = model.generate_content(full_prompt)
        return response.text
    except Exception as e:
        logger.error(f"Ошибка генерации ответа Gemini: {e}")
        return "Извините, возникла ошибка при генерации ответа."
