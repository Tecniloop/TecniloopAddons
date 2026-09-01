# Copyright 2026 Tecniloop
# License Other proprietary.

import json
import re
from datetime import date, datetime
from urllib.parse import parse_qs, unquote, urlparse


GS1_AI = {
    "01": "gtin",
    "10": "lot",
    "17": "expiry",
    "21": "serial",
    "30": "qty",
    "37": "count",
    "240": "sku",
    "400": "po",
    "415": "gln",
}


def looks_like_qr(raw):
    if not raw:
        return False
    text = str(raw).strip()
    if text.startswith("{") or "://" in text:
        return True
    if text.startswith("]Q") or text.startswith("]C"):
        return True
    if "(" in text and ")" in text and re.search(r"\(\d{2,4}\)", text):
        return True
    if len(text) >= 20 and ("GTIN" in text.upper() or "LOT" in text.upper()):
        return True
    return False


def parse_qr_payload(raw):
    """Return a dict of known keys extracted from a QR / GS1 / URL payload."""
    text = unquote(str(raw or "").strip())
    data = {"raw": text, "kind": "plain", "code": text}
    if not text:
        return data
    if text.startswith("{") and text.endswith("}"):
        try:
            payload = json.loads(text)
            if isinstance(payload, dict):
                data.update({k.lower(): v for k, v in payload.items() if v not in (None, "")})
                data["kind"] = "json"
                data["code"] = (
                    payload.get("barcode")
                    or payload.get("gtin")
                    or payload.get("sku")
                    or payload.get("code")
                    or text
                )
                return data
        except ValueError:
            pass
    if "://" in text:
        parsed = urlparse(text)
        data["kind"] = "url"
        query = {k: v[-1] for k, v in parse_qs(parsed.query).items() if v}
        data.update(query)
        path_parts = [part for part in parsed.path.split("/") if part]
        ai_map = {"01": "gtin", "10": "lot", "21": "serial", "240": "sku", "400": "po"}
        idx = 0
        while idx < len(path_parts) - 1:
            key = ai_map.get(path_parts[idx])
            if key:
                data[key] = path_parts[idx + 1]
                idx += 2
                continue
            idx += 1
        data["code"] = data.get("gtin") or data.get("sku") or data.get("serial") or (
            path_parts[-1] if path_parts else text
        )
        return data
    gs1 = _parse_gs1(text)
    if gs1:
        data.update(gs1)
        data["kind"] = "gs1"
        data["code"] = gs1.get("gtin") or gs1.get("sku") or gs1.get("serial") or text
        return data
    return data


def _parse_gs1(text):
    result = {}
    for match in re.finditer(r"\((\d{2,4})\)([^()]*)", text):
        ai, value = match.group(1), match.group(2).strip()
        key = GS1_AI.get(ai)
        if key and value:
            result[key] = value
    if result:
        return result
    # FNC1 style: 01 + 14 digits
    compact = re.sub(r"\s+", "", text)
    match = re.match(r"01(\d{14})(.*)$", compact)
    if match:
        result["gtin"] = match.group(1)
        rest = match.group(2)
        lot = re.search(r"10([A-Za-z0-9\-]{1,20})", rest)
        serial = re.search(r"21([A-Za-z0-9\-]{1,20})", rest)
        if lot:
            result["lot"] = lot.group(1)
        if serial:
            result["serial"] = serial.group(1)
        expiry = re.search(r"17(\d{6})", rest)
        if expiry:
            result["expiry"] = expiry.group(1)
    return result


def parse_expiry_value(value):
    """Accept GS1 YYMMDD, ISO dates or common EU formats."""
    if not value:
        return False
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if re.fullmatch(r"\d{6}", text):
        year = 2000 + int(text[0:2])
        month = int(text[2:4])
        day = int(text[4:6]) or 1
        try:
            return date(year, month, day)
        except ValueError:
            return False
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            continue
    return False
