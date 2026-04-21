from supabase import create_client, Client
from app.config import settings

def get_supabase() -> Client:
    # Use the service role key for backend operations
    return create_client(settings.supabase_url, settings.supabase_service_role_key)

supabase = get_supabase()
