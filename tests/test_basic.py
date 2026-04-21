import pytest
from app.utils.text_utils import normalize_name

def test_normalize_name():
    assert normalize_name("Müller GmbH") == "mueller gmbh"
    assert normalize_name("  Test  -  Firma  ") == "test firma"
    assert normalize_name("Société Anonyme") == "societe anonyme"
