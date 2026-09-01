# Copyright 2026 Tecniloop
# License Other proprietary.

import logging
import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

_logger = logging.getLogger(__name__)

VIES_URL = "https://ec.europa.eu/taxation_customs/vies/services/checkVatService"

NIF_LETTERS = "TRWAGMYFPDXBNJZSQVHLCKE"
CIF_CONTROL = "JABCDEFGHI"
CIF_LETTERS = set("ABCDEFGHJNPQRSUVW")


def compact_vat(vat):
    if not vat:
        return ""
    return re.sub(r"[^A-Za-z0-9]", "", str(vat)).upper()


def split_country_vat(vat):
    compact = compact_vat(vat)
    if len(compact) >= 3 and compact[:2].isalpha():
        return compact[:2], compact[2:]
    return "", compact


def spanish_nif_valid(body):
    """NIF (12345678Z), NIE (X1234567L) or CIF (B12345678)."""
    body = compact_vat(body)
    if not body:
        return False
    if body[0] in "XYZ":
        prefix = {"X": "0", "Y": "1", "Z": "2"}[body[0]]
        digits = prefix + body[1:-1]
        if len(body) != 9 or not digits.isdigit() or not body[-1].isalpha():
            return False
        return body[-1] == NIF_LETTERS[int(digits) % 23]
    if body[0].isdigit():
        if len(body) != 9 or not body[:8].isdigit() or not body[-1].isalpha():
            return False
        return body[-1] == NIF_LETTERS[int(body[:8]) % 23]
    if body[0] in CIF_LETTERS and len(body) == 9 and body[1:8].isdigit():
        digits = [int(d) for d in body[1:8]]
        total = 0
        for i, digit in enumerate(digits):
            if i % 2 == 0:
                doubled = digit * 2
                total += doubled // 10 + doubled % 10
            else:
                total += digit
        remainder = total % 10
        control = 0 if remainder == 0 else 10 - remainder
        last = body[-1]
        if last.isdigit():
            return int(last) == control
        return last == CIF_CONTROL[control]
    return False


def vat_looks_valid(vat):
    """Cheap format check. ES uses checksum; other EU prefixes only length."""
    country, body = split_country_vat(vat)
    if not body:
        return False
    if country in ("", "ES"):
        return spanish_nif_valid(body)
    if not country.isalpha() or len(country) != 2:
        return False
    return 8 <= len(body) <= 12


def check_vies_soap(vat, timeout=12):
    """Synchronous EU VIES checkVat. Returns True/False, or None if unavailable."""
    country, number = split_country_vat(vat)
    if not country or not number:
        return None
    envelope = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/" '
        'xmlns:urn="urn:ec.europa.eu:taxud:vies:services:checkVat:types">'
        "<soap:Body><urn:checkVat>"
        "<urn:countryCode>%s</urn:countryCode>"
        "<urn:vatNumber>%s</urn:vatNumber>"
        "</urn:checkVat></soap:Body></soap:Envelope>"
    ) % (country, number)
    request = urllib.request.Request(
        VIES_URL,
        data=envelope.encode("utf-8"),
        headers={
            "Content-Type": "text/xml; charset=utf-8",
            "SOAPAction": "",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read()
    except (urllib.error.URLError, TimeoutError) as err:
        _logger.warning("VIES SOAP unavailable for %s: %s", vat, err)
        return None
    text = body.decode("utf-8", errors="ignore")
    match = re.search(r"<valid>\s*(true|false)\s*</valid>", text, flags=re.I)
    if not match:
        try:
            root = ET.fromstring(body)
            for el in root.iter():
                if el.tag.endswith("valid") and el.text:
                    return el.text.strip().lower() == "true"
        except ET.ParseError:
            _logger.warning("VIES SOAP unreadable response for %s", vat)
            return None
        return None
    return match.group(1).lower() == "true"
