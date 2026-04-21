from typing import List
from app.services.supabase_client import supabase
from app.utils.logger import setup_logger
from app.config import settings

logger = setup_logger(__name__)

async def is_authorized(chat_id: int) -> bool:
    """Prüft, ob ein User autorisiert ist, den Bot zu nutzen."""
    
    # 1. ENV Check (schneller, für POC/Dev)
    allowed_from_env = settings.get_allowed_chat_ids()
    if allowed_from_env and chat_id in allowed_from_env:
        return True
        
    # 2. Supabase Check
    try:
        response = supabase.table('authorized_users').select('telegram_chat_id').eq('telegram_chat_id', chat_id).execute()
        if response.data and len(response.data) > 0:
            return True
        return False
    except Exception as e:
        logger.error(f"Fehler bei Auth-Prüfung in DB: {e}")
        return False
