"""
Hilfsfunktionen: Logger-Setup und Text-Utilities.
"""
import logging
import sys
import re
import unicodedata
from typing import Optional

from app.config import settings


def setup_logger(name: str) -> logging.Logger:
    """
    Erstellt einen Logger mit einheitlichem Format.
    Verwendung in jedem Modul: logger = setup_logger(__name__)
    """
    logger = logging.getLogger(name)
    
    # Verhindere doppelte Handler bei Re-Imports
    if logger.handlers:
        return logger
    
    logger.setLevel(settings.log_level.upper())
    
    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    
    # Verhindere Doppel-Logging via Root-Logger
    logger.propagate = False
    
    return logger


def normalize_vendor_name(name: str) -> str:
    """
    Normalisiert einen Lieferantennamen fuer robustes Matching.
    
    Beispiele:
        "Swisscom AG"          -> "swisscom ag"
        "Galaxus.ch"           -> "galaxus ch"
        "Bündner Werbeagentur" -> "bundner werbeagentur"
        "  DIGITEC   GALAXUS " -> "digitec galaxus"
    """
    if not name:
        return ""
    
    # Unicode normalisieren (ä -> a, é -> e, etc.)
    nfkd = unicodedata.normalize("NFKD", name)
    ascii_name = "".join(c for c in nfkd if not unicodedata.combining(c))
    
    # Lowercase
    ascii_name = ascii_name.lower()
    
    # Sonderzeichen zu Leerzeichen (. , - _ / etc.)
    ascii_name = re.sub(r"[^\w\s]", " ", ascii_name)
    
    # Mehrfach-Whitespace zusammenfassen
    ascii_name = re.sub(r"\s+", " ", ascii_name).strip()
    
    return ascii_name


def format_chf(amount: Optional[float]) -> str:
    """
    Formatiert einen Betrag als Schweizer Franken mit Tausender-Apostroph.
    
    Beispiel: 1234.5 -> "CHF 1'234.50"
    """
    if amount is None:
        return "CHF —"
    return f"CHF {amount:,.2f}".replace(",", "'")


def truncate(text: Optional[str], max_length: int = 50) -> str:
    """Kuerzt einen String mit '...' falls zu lang."""
    if not text:
        return ""
    if len(text) <= max_length:
        return text
    return text[:max_length - 3] + "..."
