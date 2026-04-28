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
    # MANUAL JOURNAL ENTRIES (Buchungssaetze ohne Bill)
    # =========================================================

    async def create_manual_journal_entry(
        self,
        date: str,
        debit_account_id: int,
        credit_account_id: int,
        amount: float,
        description: str,
        tax_id: Optional[int] = None,
        reference_nr: Optional[str] = None,
        currency_id: int = 1,
    ) -> Optional[Dict[str, Any]]:
        """
        Schreibt einen einzelnen Buchungssatz direkt in die Bexio-Buchhaltung
        ohne Umweg ueber Lieferantenrechnung.

        Use-Case: Wenn der Inhaber eine Geschaeftsausgabe privat zahlt, ist
        die korrekte Buchung 'Aufwand an Kontokorrent Inhaber'. Eine
        Lieferantenrechnung waere unsauber, weil's keinen offenen Posten
        gegen den Lieferanten gibt - wir schulden niemandem etwas (ausser
        uns selber).

        Args:
            date: Buchungsdatum YYYY-MM-DD (typischerweise Belegdatum)
            debit_account_id: Soll-Konto (Aufwand-Konto, z.B. 6500 ID)
            credit_account_id: Haben-Konto (z.B. 2100 Kontokorrent Inhaber)
            amount: Brutto-Betrag (mit MwSt). Bexio splittet via tax_id.
            description: Buchungstext, z.B. 'Beleg Migros 28.04.2026 - privat'
            tax_id: Bexio-Tax-ID fuer Vorsteuer-Split (optional). Wenn gesetzt,
                rechnet Bexio MwSt automatisch aus dem Brutto-Betrag.
            reference_nr: Externe Belegnummer (Rechnungs-Nr), optional
            currency_id: Bexio-internes Currency-ID. Default 1 = CHF.

        Returns: Bexio-Response-Dict mit der Manual-Entry-ID, oder None
                 wenn API-Fehler.
        """
        entry: Dict[str, Any] = {
            "debit_account_id": int(debit_account_id),
            "credit_account_id": int(credit_account_id),
            "amount": round(float(amount), 2),
            "currency_id": int(currency_id),
            "currency_factor": 1,
            "description": description[:200],
        }
        if tax_id is not None:
            entry["tax_id"] = int(tax_id)

        payload: Dict[str, Any] = {
            "type": "manual_single_entry",
            "date": date,
            "entries": [entry],
        }
        if reference_nr:
            payload["reference_nr"] = str(reference_nr)[:50]

        try:
            result = await self._request(
                "POST",
                "/3.0/accounting/manual_entries",
                json=payload,
            )
            entry_id = (result or {}).get("id") if isinstance(result, dict) else None
            logger.info(
                f"Bexio Manual-Journal-Entry erstellt: id={entry_id} "
                f"Soll={debit_account_id} Haben={credit_account_id} "
                f"Betrag={amount:.2f} Datum={date}"
            )
            return result if isinstance(result, dict) else None
        except BexioError as e:
            logger.error(
                f"Bexio Manual-Entry fehlgeschlagen: Soll={debit_account_id} "
                f"Haben={credit_account_id} Betrag={amount:.2f} - {e}"
            )
            raise

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
        vendor_reference: str,
        bill_date: str,
        due_date: str,
        total_amount: float,
        account_id: int,
        tax_id: Optional[int] = None,
        currency_code: str = "CHF",
        title: Optional[str] = None,
        iban: Optional[str] = None,
        qr_reference: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Erstellt eine Eingangsrechnung in Bexio.
        
        WICHTIG: Die v3 API erwartet eine komplexe Struktur mit 'line_items'.
        Wir buchen vereinfacht als EINE Position = Gesamtbetrag auf das Konto.
        
        Args:
            vendor_bexio_id: ID des Lieferanten-Kontakts in Bexio
            vendor_reference: Rechnungsnummer des Lieferanten
            bill_date: YYYY-MM-DD
            due_date: YYYY-MM-DD
            total_amount: Brutto-Betrag inkl. MwSt
            account_id: Bexio-ID des Aufwandskontos
            tax_id: Bexio-ID des MwSt-Codes
            currency_code: Default CHF
            title: Optionaler Titel der Rechnung
            iban: IBAN fuer spaetere Zahlung
            qr_reference: QR-Referenznummer
        
        Returns:
            Das erstellte Bill-Objekt mit neuer ID, oder None bei Fehler.
        """
        
        # Payload-Struktur gemaess Bexio v3 API Doku
        line_item = {
            "amount": 1,
            "unit_id": None,
            "account_id": account_id,
            "unit_price": round(total_amount, 2),
            "description": title or f"Rechnung {vendor_reference}",
        }
        
        if tax_id is not None:
            line_item["tax_id"] = tax_id
        
        payload = {
            "contact_id": vendor_bexio_id,
            "vendor_ref": vendor_reference,
            "bill_date": bill_date,
            "due_date": due_date,
            "currency_code": currency_code,
            "title": title or f"Rechnung {vendor_reference}",
            "line_items": [line_item],
        }
        
        # Optional: IBAN & QR-Referenz fuer spaetere Zahlung
        if iban:
            payload["payment"] = {
                "iban": iban.replace(" ", "").upper(),
            }
            if qr_reference:
                payload["payment"]["qr_reference"] = qr_reference
        
        try:
            result = await self._request("POST", "/3.0/purchase/bills", json=payload)
            if result:
                bill_id = result.get("id")
                logger.info(f"Bexio Bill erstellt: #{bill_id} fuer Vendor {vendor_bexio_id}, {total_amount} CHF")
                return result
            return None
        except BexioError as e:
            logger.error(f"Fehler beim Bill-Erstellen: {e.response_body or e}")
            # Reraise damit Bot den User informieren kann
            raise
    
    async def get_supplier_bill(self, bill_id: int) -> Optional[Dict[str, Any]]:
        """Holt eine bestehende Bill zur Verifikation."""
        try:
            return await self._request("GET", f"/3.0/purchase/bills/{bill_id}")
        except BexioError as e:
            logger.error(f"Fehler beim Bill-Abruf {bill_id}: {e}")
            return None
    
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
