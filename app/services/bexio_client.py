import httpx
from typing import Dict, Any, List, Optional
from app.config import settings
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

class BexioAPIError(Exception):
    pass

class BexioClient:
    def __init__(self):
        self.base_url = settings.bexio_api_base_url
        self.headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {settings.bexio_api_token}"
        }
        self.timeout = 30.0

    async def get_accounts(self) -> List[Dict[str, Any]]:
        url = f"{self.base_url}/2.0/accounts"
        return await self._request("GET", url)

    async def get_taxes(self) -> List[Dict[str, Any]]:
        url = f"{self.base_url}/3.0/taxes"
        return await self._request("GET", url)
        
    async def get_contacts(self, query: str = None) -> List[Dict[str, Any]]:
        url = f"{self.base_url}/2.0/contact"
        params = {}
        if query:
            # Vereinfachung: In Realität evtl search endpoint nutzen oder lokal filtern
            params['name'] = query
        return await self._request("GET", url, params=params)

    async def create_contact(self, name: str) -> Dict[str, Any]:
        url = f"{self.base_url}/2.0/contact"
        payload = {
            "contact_type_id": 2, # 2=Firma (meistens bei Lieferanten)
            "name_1": name,
            "owner_id": 1 # Standard owner, müsste in der Praxis configuriert werden
        }
        return await self._request("POST", url, json=payload)

    async def create_bill(self, vendor_id: int, title: str, 
                         vendor_ref: str, date: str, due_date: str, 
                         positions: List[Dict[str, Any]]) -> Dict[str, Any]:
        url = f"{self.base_url}/3.0/purchase/bills" # V3 endpoint
        payload = {
            "vendor_id": vendor_id,
            "title": title,
            "vendor_reference": vendor_ref,
            "document_date": date,
            "due_date": due_date,
            "positions": positions
        }
        return await self._request("POST", url, json=payload)

    async def _request(self, method: str, url: str, params: dict = None, json: dict = None) -> Any:
        async with httpx.AsyncClient() as client:
            try:
                response = await client.request(
                    method=method,
                    url=url,
                    headers=self.headers,
                    params=params,
                    json=json,
                    timeout=self.timeout
                )
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as e:
                logger.error(f"Bexio API HTTP Error: {e.response.text}")
                raise BexioAPIError(f"Bexio API Fehler ({e.response.status_code}): {e.response.text}")
            except httpx.RequestError as e:
                logger.error(f"Bexio Connection Error: {e}")
                raise BexioAPIError(f"Verbindungsfehler zu Bexio: {e}")

bexio_client = BexioClient()
