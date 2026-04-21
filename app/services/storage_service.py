import uuid
from datetime import datetime
from app.services.supabase_client import supabase
from app.config import settings

class StorageError(Exception):
    pass

async def upload_invoice(file_bytes: bytes, original_name: str, mime_type: str) -> str:
    """Lädt ein PDF/Bild in den Supabase Storage hoch und gibt den Path zurück."""
    try:
        now = datetime.now()
        month_str = now.strftime("%Y-%m")
        file_ext = "pdf" if mime_type == "application/pdf" else "jpg" # Vereinfacht
        file_uuid = str(uuid.uuid4())
        
        path = f"{month_str}/{file_uuid}.{file_ext}"
        
        supabase.storage.from_(settings.supabase_storage_bucket).upload(
            file=file_bytes,
            path=path,
            file_options={"content-type": mime_type}
        )
        return path
    except Exception as e:
        raise StorageError(f"Fehler beim Upload in Supabase Storage: {e}")
