# app/services/telegram_service.py
import httpx
import logging

logger = logging.getLogger(__name__)

class TelegramService:
    @staticmethod
    async def send_message(token: str, chat_id: str, message: str):
        """Enviar mensaje asíncrono a Telegram"""
        if not token or not chat_id:
            logger.warning("Intentando enviar mensaje de Telegram sin token o chat_id")
            return
        
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML"
        }
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=payload, timeout=10.0)
                response.raise_for_status()
                return True
        except Exception as e:
            logger.error(f"Error enviando mensaje a Telegram: {str(e)}")
            return False

telegram_service = TelegramService()
