from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional, List

class Settings(BaseSettings):
    # Telegram
    telegram_bot_token: str
    telegram_allowed_chat_ids: str = ""
    
    # Bexio
    bexio_api_token: str
    bexio_api_base_url: str = "https://api.bexio.com"
    
    # Supabase
    supabase_url: str
    supabase_service_role_key: str
    supabase_storage_bucket: str = "invoices"
    
    # Gemini
    gemini_api_key: str
    gemini_model: str = "gemini-2.5-flash"
    
    # App
    log_level: str = "INFO"
    environment: str = "production"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    def get_allowed_chat_ids(self) -> List[int]:
        if not self.telegram_allowed_chat_ids:
            return []
        return [int(x.strip()) for x in self.telegram_allowed_chat_ids.split(",") if x.strip().isdigit()]

settings = Settings()
