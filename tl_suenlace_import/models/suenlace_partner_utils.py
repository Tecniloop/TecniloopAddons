# Copyright 2026 Tecniloop
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
"""Utilidades de normalización para terceros SUENLACE.

No dependen del ORM para que puedan reutilizarse y probarse de forma aislada.
"""
import re
import unicodedata


_SPANISH_COUNTRY_CODES = {"011", "ES", "ESP", "724"}
_SPANISH_NIF_RE = re.compile(
    r"^(?:"
    r"\d{8}[A-Z]"                 # DNI
    r"|[XYZ]\d{7}[A-Z]"          # NIE
    r"|[KLM]\d{7}[A-Z]"          # NIF especiales de persona física
    r"|[ABCDEFGHJNPQRSUVW]\d{7}[0-9A-J]"  # CIF/NIF entidad
    r")$"
)


def compact_vat(value):
    """Devuelve el identificador fiscal en mayúsculas y sin separadores."""
    return re.sub(r"[^A-Z0-9]", "", (value or "").upper())


def normalize_vat(value, country_code=None):
    """Normaliza el NIF/VAT y añade ``ES`` a los NIF españoles.

    El origen puede enviar el NIF con o sin ``ES`` y con separadores. Si el
    país indica expresamente un país no español, se conserva el identificador
    internacional sin forzar el prefijo español.
    """
    value = compact_vat(value)
    if not value:
        return ""

    country = compact_vat(country_code)
    if value.startswith("ES"):
        local = value[2:]
        return "ES%s" % local if local else ""

    if country and country not in _SPANISH_COUNTRY_CODES:
        return value

    if country in _SPANISH_COUNTRY_CODES or _SPANISH_NIF_RE.match(value):
        return "ES%s" % value
    return value


def vat_local_part(value, country_code=None):
    """Devuelve la parte nacional para búsquedas con/sin prefijo ``ES``."""
    normalized = normalize_vat(value, country_code=country_code)
    return normalized[2:] if normalized.startswith("ES") else normalized


def vat_equivalent(left, right, left_country=None, right_country=None):
    """Compara dos identificadores fiscales tras normalizarlos."""
    if not left or not right:
        return False
    return normalize_vat(left, left_country) == normalize_vat(
        right, right_country)


def infer_company_type(vat):
    """Distingue de forma conservadora persona física y entidad española."""
    local = vat_local_part(vat)
    if re.match(r"^(?:\d{8}[A-Z]|[XYZKLM]\d{7}[A-Z])$", local):
        return "person"
    return "company"


def normalize_name(value):
    """Normaliza un nombre para comparar sin acentos ni puntuación."""
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = re.sub(r"[^A-Z0-9]+", " ", value.upper()).strip()
    return re.sub(r"\s+", " ", value)


def normalize_phone(value):
    """Conserva únicamente dígitos para comparar teléfonos."""
    return re.sub(r"\D", "", value or "")


def normalize_bank_account(value):
    """Normaliza CCC/IBAN eliminando espacios y separadores."""
    return re.sub(r"[^A-Z0-9]", "", (value or "").upper())
