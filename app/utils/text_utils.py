import re

def normalize_name(name: str) -> str:
    """Normalisiert einen Lieferantennamen für das Matching."""
    if not name:
        return ""
    # Kleinbuchstaben
    name = name.lower()
    # Umlaute ersetzen
    replacements = {'ä': 'ae', 'ö': 'oe', 'ü': 'ue', 'ß': 'ss', 'é': 'e', 'è': 'e', 'à': 'a'}
    for k, v in replacements.items():
        name = name.replace(k, v)
    # Sonderzeichen entfernen und trimmen
    name = re.sub(r'[^a-z0-9\s]', '', name)
    # Mehrfache Leerzeichen entfernen
    name = re.sub(r'\s+', ' ', name)
    return name.strip()
