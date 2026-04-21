"""
Supabase Storage Wrapper fuer File-Uploads (PDFs, Bilder).
"""
from datetime import datetime, timezone
from typing import Optional, Tuple
from uuid import uuid4

from app.config import settings
from app.db import get_client
from app.utils import setup_logger


logger = setup_logger(__name__)


def upload_invoice_file(
    file_bytes: bytes,
    original_filename: str,
    mime_type: str = "application/pdf",
) -> Optional[str]:
    """
    Laedt eine Rechnungs-Datei in den Supabase Storage Bucket 'invoices'.
    
    Pfad-Schema: {YYYY-MM}/{uuid}.{ext}
    Beispiel: "2026-04/a3f8-b2c1-....pdf"
    
    Returns: Storage-Pfad fuer spaeteren Download oder None bei Fehler.
    """
    try:
        # Extension aus Filename oder Mime-Type ableiten
        extension = _extension_from_mime(mime_type, original_filename)
        
        # Pfad bauen: 2026-04/<uuid>.pdf
        date_folder = datetime.now(timezone.utc).strftime("%Y-%m")
        unique_id = uuid4().hex
        file_path = f"{date_folder}/{unique_id}.{extension}"
        
        # Upload
        client = get_client()
        client.storage.from_(settings.supabase_storage_bucket).upload(
            path=file_path,
            file=file_bytes,
            file_options={
                "content-type": mime_type,
                "upsert": "false",  # Darf nicht existieren (UUID ist unique)
            }
        )
        
        logger.info(f"File hochgeladen: {file_path} ({len(file_bytes)} bytes)")
        return file_path
    except Exception as e:
        logger.error(f"Fehler beim File-Upload: {e}")
        return None


def download_invoice_file(file_path: str) -> Optional[bytes]:
    """Laedt eine Datei aus dem Bucket. Returns: bytes oder None."""
    try:
        client = get_client()
        data = client.storage.from_(settings.supabase_storage_bucket).download(file_path)
        return data
    except Exception as e:
        logger.error(f"Fehler beim File-Download {file_path}: {e}")
        return None


def get_signed_url(file_path: str, expires_in: int = 3600) -> Optional[str]:
    """
    Erstellt eine zeitlich limitierte URL (default 1h) fuer den File-Download.
    Nuetzlich fuer spaeteres Web-Dashboard.
    """
    try:
        client = get_client()
        result = client.storage.from_(settings.supabase_storage_bucket).create_signed_url(
            path=file_path,
            expires_in=expires_in,
        )
        return result.get("signedURL")
    except Exception as e:
        logger.error(f"Fehler beim Signed-URL erstellen: {e}")
        return None


def _extension_from_mime(mime_type: str, filename: str) -> str:
    """Leitet die Extension aus Mime-Type oder Filename ab."""
    mime_map = {
        "application/pdf": "pdf",
        "image/jpeg": "jpg",
        "image/jpg": "jpg",
        "image/png": "png",
        "image/heic": "heic",
        "image/heif": "heic",
    }
    if mime_type in mime_map:
        return mime_map[mime_type]
    
    # Fallback: Extension aus Filename
    if filename and "." in filename:
        ext = filename.rsplit(".", 1)[-1].lower()
        if ext in ("pdf", "jpg", "jpeg", "png", "heic", "heif"):
            return ext
    
    # Letzter Fallback
    return "bin"
