"""
Bexio REST API Client.
Behandelt v2/v3 Mix, Rate-Limiting, Retries und saubere Error-Messages.
"""
import asyncio
from typing import Optional, List, Dict, Any

import httpx

from app.config import settings
from app.utils import setup_logger, normalize_vendor_name


logger = setup_logger(__name__)


class BexioError(Exception):
    """Custom Exception fuer Bexio-API Fehler."""
    
    def __init__(self, message: str, status_code: Optional[int] = None, response_body: Optional[str] = None):
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


class BexioClient:
    """
    Async HTTP-Client fuer Bexio API.
    Nutzt einen persistenten httpx.AsyncClient fuer Connection-Pooling.
    """
    
    def __init__(self):
        self.base_url = settings.bexio_api_base_url.rstrip("/")
        self.headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {settings.bexio_api_token}",
        }
        self._client: Optional[httpx.AsyncClient] = None
    
    async def _get_client(self) -> httpx.AsyncClient:
        """Lazy-init, damit der Client nicht bei Import schon erstellt wird."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                headers=self.headers,
                timeout=httpx.Timeout(30.0, connect=10.0),
                limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
            )
        return self._client
    
    async def close(self):
        """Graceful Shutdown - wird beim Bot-Stop aufgerufen."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
    
    async def _request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        json: Optional[Dict[str, Any]] = None,
        max_retries: int = 2,
    ) -> Any:
        """
        Generische Request-Methode mit Retry-Logik.
        Retries bei 429 (Rate Limit) und 5xx Errors.
        """
        url = f"{self.base_url}{path}"
        client = await self._get_client()
        
        last_error: Optional[Exception] = None
        
        for attempt in range(max_retries + 1):
            try:
                response = await client.request(
                    method=method,
                    url=url,
                    params=params,
                    json=json,
                )
                
                # Rate-Limit handhaben
                if response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", 5))
                    logger.warning(f"Rate-Limit erreicht, warte {retry_after}s")
                    await asyncio.sleep(retry_after)
                    continue
                
                # Server-Fehler: retry
                if 500 <= response.status_code < 600:
                    if attempt < max_retries:
                        wait = 2 ** attempt
                        logger.warning(f"Server-Fehler {response.status_code}, retry in {wait}s")
                        await asyncio.sleep(wait)
                        continue
                
                # Keine Retry - entweder OK oder Client-Error
                if response.is_success:
                    # Leere Response bei 204 No Content
                    if response.status_code == 204 or not response.content:
                        return None
                    return response.json()
                
                # Client-Error (4xx) - kein Retry, werfen
                error_body = response.text
                logger.error(
                    f"Bexio API Fehler {response.status_code} bei {method} {path}: {error_body}"
                )
                raise BexioError(
                    message=f"Bexio API Fehler ({response.status_code})",
                    status_code=response.status_code,
                    response_body=error_body,
                )
            
            except httpx.TimeoutException as e:
                last_error = e
                if attempt < max_retries:
                    logger.warning(f"Timeout bei {method} {path}, retry {attempt + 1}/{max_retries}")
                    await asyncio.sleep(2 ** attempt)
                    continue
                raise BexioError(f"Bexio Timeout nach {max_retries + 1} Versuchen: {e}")
            
            except httpx.RequestError as e:
                last_error = e
                if attempt < max_retries:
                    logger.warning(f"Connection-Fehler: {e}, retry")
                    await asyncio.sleep(2 ** attempt)
                    continue
                raise BexioError(f"Bexio Verbindungsfehler: {e}")
        
        # Sollte theoretisch unerreichbar sein
        raise BexioError(f"Max Retries erreicht: {last_error}")
    
    # =========================================================
    # KONTENPLAN
    # =========================================================
    
    async def list_accounts(self) -> List[Dict[str, Any]]:
        """
        Holt den kompletten Kontenplan.
        Response-Format (v2):
        [
          {
            "id": 123,
            "account_no": "4400",
            "name": "Materialaufwand",
            "account_type": 5,
            "is_active": true,
            ...
          }
        ]
        """
        # Bexio paginiert manchmal, wir ziehen max 2000
        result = await self._request("GET", "/2.0/accounts", params={"limit": 2000})
        return result if isinstance(result, list) else []
    
    # =========================================================
    # MWST-CODES
    # =========================================================
    
    async def list_taxes(self) -> List[Dict[str, Any]]:
        """
        Holt alle MwSt-Codes.
        v3 Response-Format:
        [
          {
            "id": 1,
            "code": "VSTN",
            "name": "Vorsteuer Normal 8.1%",
            "value": 8.1,
            "type": "pre_tax",
            "is_active": true
          }
        ]
        """
        result = await self._request("GET", "/3.0/taxes", params={"limit": 500})
        return result if isinstance(result, list) else []
    
    # =========================================================
    # KONTAKTE / LIEFERANTEN
    # =========================================================
    
    async def search_contacts(self, name: str) -> List[Dict[str, Any]]:
        """
        Sucht Kontakte ueber den Namen.
        Bexio v2 hat zwei Suchwege - wir probieren zuerst den Standard-Filter.
        """
        try:
            # Methode 1: Query-Param (filtert nach name_1)
            result = await self._request(
                "GET",
                "/2.0/contact",
                params={"name_1_like": name, "limit": 50},
            )
            if result and isinstance(result, list):
                return result
        except BexioError as e:
            logger.warning(f"Contact-Search v1 failed: {e}, versuche Alternative")
        
        # Methode 2: Alle laden und lokal filtern (Fallback)
        try:
            all_contacts = await self._request(
                "GET",
                "/2.0/contact",
                params={"limit": 2000},
            )
            if not all_contacts:
                return []
            
            normalized_query = normalize_vendor_name(name)
            matches = []
            for contact in all_contacts:
                contact_name = contact.get("name_1", "")
                if normalize_vendor_name(contact_name) == normalized_query:
                    matches.append(contact)
            return matches
        except BexioError as e:
            logger.error(f"Contact-Search fallback failed: {e}")
            return []
    
    async def create_supplier_contact(
        self,
        name: str,
        uid_number: Optional[str] = None,
        iban: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Erstellt einen neuen Lieferanten-Kontakt in Bexio.
        contact_type_id=2 bedeutet "Firma".
        """
        # Owner-ID: wir nehmen die des aktuellen API-Users (via Profile)
        owner_id = await self._get_current_user_id()
        
        payload = {
            "contact_type_id": 2,  # 2 = Firma
            "name_1": name,
            "owner_id": owner_id,
            "user_id": owner_id,
        }
        
        if uid_number:
            payload["remarks"] = f"UID: {uid_number}"
        
        try:
            result = await self._request("POST", "/2.0/contact", json=payload)
            if result:
                logger.info(f"Kontakt in Bexio erstellt: {name} (ID {result.get('id')})")
                return result
            return None
        except BexioError as e:
            logger.error(f"Fehler beim Kontakt-Erstellen '{name}': {e}")
            return None
    
    async def _get_current_user_id(self) -> int:
        """
        Holt die User-ID des API-Users.
        Wird als owner_id fuer erstellte Kontakte gebraucht.
        Fallback auf 1 falls nicht ermittelbar.
        """
        try:
            result = await self._request("GET", "/3.0/users/me")
            if result and "id" in result:
                return result["id"]
        except BexioError:
            pass
        
        # Fallback: ersten User aus der Liste
        try:
            users = await self._request("GET", "/3.0/users")
            if users and isinstance(users, list) and len(users) > 0:
                return users[0]["id"]
        except BexioError:
            pass
        
        logger.warning("User-ID nicht ermittelbar, nutze Fallback 1")
        return 1
    
    # =========================================================
    # EINGANGSRECHNUNGEN (SUPPLIER BILLS)
    # =========================================================
    
    async def create_supplier_bill(
        self,
        vendor_bexio_id: int,
        vendor_name: str,
        vendor_reference: str,
        bill_date: str,
        due_date: str,
        total_amount: float,
        account_id: int,
        tax_id: Optional[int] = None,
        currency_code: str = "CHF",
        title: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Erstellt eine Eingangsrechnung (Kreditor) in Bexio via v4 API.

        Bexio hat den Endpoint fuer Supplier-Bills in v4 verschoben.
        Der v3-Endpoint existiert nicht mehr und liefert 404.

        Wir buchen vereinfacht als EINE Position = Gesamtbetrag auf das Konto
        mit manual_amount=false und item_net=false (Betraege inkl. MwSt).

        Args:
            vendor_bexio_id: ID des Lieferanten-Kontakts in Bexio
            vendor_name: Name des Lieferanten (fuer address.lastname_company)
            vendor_reference: Rechnungsnummer des Lieferanten
            bill_date: YYYY-MM-DD
            due_date: YYYY-MM-DD
            total_amount: Brutto-Betrag inkl. MwSt
            account_id: Bexio-ID des Aufwandskontos
            tax_id: Bexio-ID des MwSt-Codes
            currency_code: Default CHF
            title: Optionaler Titel der Rechnung

        Returns:
            Das erstellte Bill-Objekt mit neuer ID, oder None bei Fehler.
        """
        gross_amount = round(total_amount, 2)
        bill_title = title or f"Rechnung {vendor_reference}"

        line_item: Dict[str, Any] = {
            "position": 0,
            "amount": gross_amount,
            "title": bill_title,
            "booking_account_id": account_id,
        }
        if tax_id is not None:
            line_item["tax_id"] = tax_id

        payload: Dict[str, Any] = {
            "supplier_id": vendor_bexio_id,
            # Bexio erwartet contact_partner_id; wenn der Lieferant eine Firma
            # ohne Ansprechpartner ist, nutzen wir den Supplier-Kontakt selbst.
            "contact_partner_id": vendor_bexio_id,
            "currency_code": currency_code,
            "address": {
                "lastname_company": vendor_name,
                "type": "COMPANY",
            },
            "bill_date": bill_date,
            "due_date": due_date,
            "manual_amount": False,
            "item_net": False,
            "line_items": [line_item],
            "discounts": [],
            "attachment_ids": [],
            "vendor_ref": vendor_reference,
            "title": bill_title,
            "amount_calc": gross_amount,
        }

        try:
            result = await self._request("POST", "/4.0/purchase/bills", json=payload)
        except BexioError as e:
            logger.error(f"Fehler beim Bill-Erstellen: {e.response_body or e}")
            raise

        if not result:
            return None

        bill_id = result.get("id")
        logger.info(f"Bexio Bill erstellt (DRAFT): #{bill_id} fuer Vendor {vendor_bexio_id}, {gross_amount} CHF")

        # Bexio v4 erstellt die Bill als DRAFT - sie ist im UI sichtbar aber
        # NICHT im Kontenblatt verbucht. Wir transitionen direkt auf BOOKED,
        # damit die Buchung in der Buchhaltung landet.
        if bill_id:
            try:
                await self._request("PUT", f"/4.0/purchase/bills/{bill_id}/bookings/BOOKED")
                logger.info(f"Bexio Bill #{bill_id} auf BOOKED transitioned")
            except BexioError as book_err:
                logger.error(
                    f"Bill #{bill_id} als DRAFT erstellt, aber Buchungs-Transition "
                    f"fehlgeschlagen: {book_err.response_body or book_err}"
                )
                raise BexioError(
                    f"Bill als DRAFT erstellt (ID {bill_id}), aber automatische Buchung "
                    f"fehlgeschlagen. Bitte in Bexio manuell buchen oder loeschen. "
                    f"Detail: {book_err}",
                    status_code=book_err.status_code,
                    response_body=book_err.response_body,
                )

        return result

    async def get_supplier_bill(self, bill_id) -> Optional[Dict[str, Any]]:
        """Holt eine bestehende Bill zur Verifikation."""
        try:
            return await self._request("GET", f"/4.0/purchase/bills/{bill_id}")
        except BexioError as e:
            logger.error(f"Fehler beim Bill-Abruf {bill_id}: {e}")
            return None

    async def list_supplier_bills_page(
        self,
        page: int = 1,
        limit: int = 500,
        bill_date_start: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Listet Supplier-Bills paginiert (v4).
        Returns: {"data": [BillListItem...], "paging": {...}}
        WICHTIG: list-items enthalten KEINE line_items / supplier_id - dafuer
        get_supplier_bill(id) nutzen.
        """
        params: Dict[str, Any] = {
            "limit": limit,
            "page": page,
            "order": "desc",
            "sort": "bill_date",
        }
        if bill_date_start:
            params["bill_date_start"] = bill_date_start
        result = await self._request("GET", "/4.0/purchase/bills", params=params)
        if isinstance(result, dict):
            return result
        if isinstance(result, list):
            # Falls Bexio mal ohne Envelope antwortet
            return {"data": result, "paging": {}}
        return {"data": [], "paging": {}}

    async def list_contacts_page(
        self,
        offset: int = 0,
        limit: int = 2000,
    ) -> List[Dict[str, Any]]:
        """Listet Kontakte paginiert (v2, offset-basiert)."""
        try:
            result = await self._request(
                "GET", "/2.0/contact",
                params={"limit": limit, "offset": offset, "order_by": "id"},
            )
            return result if isinstance(result, list) else []
        except BexioError as e:
            logger.error(f"Fehler beim Contact-Listing offset={offset}: {e}")
            return []
    
    # =========================================================
    # BANK-KONTEN (fuer Payment-Info)
    # =========================================================
    
    async def list_bank_accounts(self) -> List[Dict[str, Any]]:
        """Listet Bank-Konten. Wird spaeter fuer Zahlungsvorschlaege gebraucht."""
        try:
            result = await self._request("GET", "/3.0/banking/accounts")
            return result if isinstance(result, list) else []
        except BexioError:
            return []


# =========================================================
# SINGLETON-INSTANZ
# =========================================================

# Ein globaler Client fuer die ganze App.
# Import und nutzen: `from app.bexio import bexio; await bexio.list_accounts()`
bexio = BexioClient()
