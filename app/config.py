"""
Zentrale Konfiguration via Pydantic Settings.
Laedt alle ENV-Variablen typsicher und validiert sie beim Start.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from typing import List


class Settings(BaseSettings):
    """Alle ENV-Variablen des Projekts. Pydantic validiert diese beim Start."""
    
    # Telegram
    telegram_bot_token: str = Field(..., description="Bot-Token von BotFather")
    telegram_allowed_chat_ids: str = Field(
        default="",
        description="Komma-separierte Liste erlaubter Chat-IDs"
    )
    
    # Bexio
    bexio_api_token: str = Field(..., description="Bexio Personal Access Token")
    bexio_api_base_url: str = Field(default="https://api.bexio.com")
    
    # Supabase
    supabase_url: str = Field(..., description="Supabase Project URL")
    supabase_service_role_key: str = Field(..., description="Supabase Service Role Key (NICHT anon!)")
    supabase_storage_bucket: str = Field(default="invoices")
    
    # Gemini
    gemini_api_key: str = Field(..., description="Google AI Studio API Key")
    gemini_model: str = Field(default="gemini-2.5-flash")
    
    # App
    log_level: str = Field(default="INFO")
    environment: str = Field(default="development")
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )
    
    @property
    def allowed_chat_ids_list(self) -> List[int]:
        """Parse die komma-separierte Liste in Integer-Liste."""
        if not self.telegram_allowed_chat_ids:
            return []
        return [
            int(cid.strip()) 
            for cid in self.telegram_allowed_chat_ids.split(",") 
            if cid.strip()
        ]
    
    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"


# Singleton: einmal laden, ueberall importieren
settings = Settings()
