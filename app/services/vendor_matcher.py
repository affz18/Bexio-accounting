from typing import Optional, Dict, Any
from app.services.supabase_client import supabase
from app.utils.text_utils import normalize_name
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

async def find_vendor(vendor_name: str) -> Optional[Dict[str, Any]]:
    """Sucht einen Lieferanten in der Supabase DB anhand des Namens."""
    if not vendor_name:
        return None
        
    normalized = normalize_name(vendor_name)
    if not normalized:
        return None
        
    try:
        # Exaktes Match auf normalisiertem Namen
        response = supabase.table('vendors').select('*').eq('normalized_name', normalized).execute()
        if response.data:
            return response.data[0]
            
        # Optional: Fuzzy Suche oder Suche nach IBAN/UID könnte hier folgen
        
        return None
    except Exception as e:
        logger.error(f"Fehler bei Vendor-Suche: {e}")
        return None
