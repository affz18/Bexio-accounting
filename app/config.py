"""
Zentrale Konfiguration via Pydantic Settings.
Laedt alle ENV-Variablen typsicher und validiert sie beim Start.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from typing import List, Optional


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

    # IMAP (Hostpoint Inbox-Scan)
    imap_enabled: bool = Field(default=False, description="IMAP-Polling aktivieren")
    imap_host: str = Field(default="imap.mail.hostpoint.ch")
    imap_port: int = Field(default=993)
    imap_user: str = Field(default="", description="IMAP-Benutzer (Mail-Adresse)")
    imap_password: str = Field(default="", description="IMAP-Passwort (App-spezifisch empfohlen)")
    imap_folder: str = Field(default="INBOX")
    imap_poll_interval_seconds: int = Field(default=60)
    imap_keywords_regex: str = Field(
        default=r"rechnung|invoice|quittung|beleg|gutschrift|kreditrechnung|bill|receipt|fattura|facture",
        description="Case-insensitive Regex auf Subject+Body"
    )
    telegram_notify_chat_id: str = Field(
        default="",
        description="Chat-ID fuer IMAP-Benachrichtigungen. Leer = erste aus telegram_allowed_chat_ids"
    )
    
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

    @property
    def imap_notify_chat_id(self) -> Optional[int]:
        """
        Chat-ID fuer IMAP-Benachrichtigungen.
        Faellt auf erste allowed_chat_id zurueck wenn telegram_notify_chat_id leer.
        """
        if self.telegram_notify_chat_id.strip():
            try:
                return int(self.telegram_notify_chat_id.strip())
            except ValueError:
                return None
        ids = self.allowed_chat_ids_list
        return ids[0] if ids else None


# Singleton: einmal laden, ueberall importieren
settings = Settings()
