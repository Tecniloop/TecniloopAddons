import datetime as dt
import decimal
import posixpath
import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple


IMAGE_EXTENSIONS = {".bmp", ".gif", ".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp"}


class BC3ParseError(Exception):
    """Raised when a BC3 file cannot be parsed safely."""


def sanitize_text(value):
    if value is None:
        return ""
    if not isinstance(value, str):
        value = str(value)
    return "".join(ch for ch in value if ch in ("\t", "\n", "\r") or ord(ch) >= 32)


def to_float(value):
    value = sanitize_text(value).strip()
    if not value:
        return 0.0
    if "," in value and "." not in value:
        value = value.replace(",", ".")
    try:
        return float(decimal.Decimal(value))
    except decimal.InvalidOperation:
        return 0.0


def parse_bc3_date(value: str) -> Optional[dt.date]:
    value = re.sub(r"\D", "", value or "")
    if not value:
        return None
    if len(value) % 2 == 1:
        value = "0" + value
    try:
        if len(value) <= 2:
            yy = int(value)
            return dt.date(1900 + yy if yy >= 80 else 2000 + yy, 1, 1)
        if len(value) <= 4:
            month = int(value[:-2] or "1") or 1
            yy = int(value[-2:])
            return dt.date(1900 + yy if yy >= 80 else 2000 + yy, month, 1)
        if len(value) <= 6:
            day = int(value[0:2]) or 1
            month = int(value[2:4]) or 1
            yy = int(value[4:6])
            return dt.date(1900 + yy if yy >= 80 else 2000 + yy, month, day)
        day = int(value[0:2]) or 1
        month = int(value[2:4]) or 1
        year = int(value[4:8])
        return dt.date(year, month, day)
    except ValueError:
        return None


@dataclass
class ParsedRecord:
    sequence: int
    record_type: str
    fields: List[str]
    raw: str


@dataclass
class ParsedMediaRef:
    code: str
    filename: str
    source: str
    type_code: str = ""
    description: str = ""
    url_ext: str = ""

    @property
    def extension(self):
        return posixpath.splitext((self.filename or "").lower())[1]

    @property
    def is_image(self):
        return self.extension in IMAGE_EXTENSIONS


@dataclass
class ParsedConcept:
    code: str
    aliases: List[str] = field(default_factory=list)
    unit: str = ""
    summary: str = ""
    prices: List[float] = field(default_factory=list)
    price_dates: List[str] = field(default_factory=list)
    concept_type: str = ""
    text: str = ""
    technical: Dict[str, str] = field(default_factory=dict)
    media_refs: List[ParsedMediaRef] = field(default_factory=list)


@dataclass
class ParsedDecompositionLine:
    parent_code: str
    child_code: str
    sequence: int
    factor: float = 1.0
    performance: float = 1.0
    percent_codes: str = ""


@dataclass
class ParsedMeasurementItem:
    line_type: str = ""
    comment: str = ""
    bim_id: str = ""
    units: float = 0.0
    length: float = 0.0
    width: float = 0.0
    height: float = 0.0
    subtotal: float = 0.0


@dataclass
class ParsedMeasurement:
    parent_code: str
    child_code: str
    position_path: str
    measurement_total: float
    label: str = ""
    items: List[ParsedMeasurementItem] = field(default_factory=list)


@dataclass
class ParsedBC3:
    name: str = ""
    encoding: str = "cp850"
    property_file: str = ""
    version: str = ""
    program: str = ""
    charset: str = ""
    comment: str = ""
    info_type: str = ""
    certification_number: str = ""
    certification_date: Optional[dt.date] = None
    url_base: str = ""
    raw_k: str = ""
    k_ci: float = 0.0
    k_gg: float = 0.0
    k_bi: float = 0.0
    k_baja: float = 0.0
    k_iva: float = 0.0
    k_currency: str = ""
    k_decimal_profile: str = ""
    record_stats: Dict[str, int] = field(default_factory=dict)
    parametric_records: List[str] = field(default_factory=list)
    records: List[ParsedRecord] = field(default_factory=list)
    concepts: Dict[str, ParsedConcept] = field(default_factory=dict)
    decomposition_lines: List[ParsedDecompositionLine] = field(default_factory=list)
    measurements: List[ParsedMeasurement] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


class BC3Parser:
    ENCODING_MAP = {
        "ANSI": "cp1252",
        "850": "cp850",
        "437": "cp437",
    }

    def parse(self, bc3_bytes: bytes, filename: str = "") -> ParsedBC3:
        raw = (bc3_bytes or b"").rstrip(b"\x1a")
        if not raw:
            raise BC3ParseError("The BC3 file is empty.")
        encoding, charset = self._detect_encoding(raw)
        text = sanitize_text(raw.decode(encoding, errors="replace"))
        data = ParsedBC3(name=filename, encoding=encoding, charset=charset)
        for record in self._iter_records(text):
            data.records.append(record)
            data.record_stats[record.record_type] = data.record_stats.get(record.record_type, 0) + 1
            try:
                self._parse_record(record, data)
            except Exception as exc:
                data.warnings.append("Cannot parse ~%s record %s: %s" % (record.record_type, record.sequence, exc))
        if not data.concepts:
            raise BC3ParseError("No ~C concept records were found.")
        return data

    def _detect_encoding(self, raw: bytes) -> Tuple[str, str]:
        probe = sanitize_text(raw[:50000].decode("latin1", errors="ignore"))
        charset = ""
        for record in self._iter_records(probe):
            if record.record_type == "V":
                charset = self._field(record.fields, 5).strip().upper()
                break
        return self.ENCODING_MAP.get(charset, "cp850"), charset or "850"

    def _iter_records(self, text: str) -> Iterable[ParsedRecord]:
        seq = 0
        for chunk in sanitize_text(text).split("~"):
            chunk = chunk.lstrip("\ufeff \t\r\n")
            if not chunk:
                continue
            fields = chunk.split("|")
            if not fields:
                continue
            header = fields[0].strip().upper()
            if not header:
                continue
            seq += 1
            yield ParsedRecord(sequence=seq, record_type=header[0], fields=fields, raw=chunk)

    def _parse_record(self, record: ParsedRecord, data: ParsedBC3):
        if record.record_type == "V":
            self._parse_v(record.fields, data)
        elif record.record_type == "K":
            self._parse_k(record.fields, record.raw, data)
        elif record.record_type == "C":
            concept = self._parse_c(record.fields)
            if concept.code:
                data.concepts[concept.code] = concept
                for alias in concept.aliases:
                    data.concepts.setdefault(alias, concept)
        elif record.record_type == "T":
            self._parse_t(record.fields, data)
        elif record.record_type == "X":
            self._parse_x(record.fields, data)
        elif record.record_type == "G":
            self._parse_g(record.fields, data)
        elif record.record_type == "F":
            self._parse_f(record.fields, data)
        elif record.record_type == "D":
            data.decomposition_lines.extend(self._parse_d(record.fields))
        elif record.record_type in ("M", "N"):
            data.measurements.append(self._parse_m(record.fields))
        elif record.record_type == "P":
            data.parametric_records.append(record.raw)

    def _parse_v(self, fields: List[str], data: ParsedBC3):
        data.property_file = self._field(fields, 1).strip()
        data.version = self._first_subfield(self._field(fields, 2))
        data.program = self._field(fields, 3).strip()
        data.charset = self._field(fields, 5).strip() or data.charset
        data.comment = self._field(fields, 6).strip()
        data.info_type = self._field(fields, 7).strip()
        data.certification_number = self._field(fields, 8).strip()
        data.certification_date = parse_bc3_date(self._field(fields, 9))
        data.url_base = self._field(fields, 10).strip()

    def _parse_k(self, fields: List[str], raw: str, data: ParsedBC3):
        """Parse the FIEBDC ~K record enough for budgeting/certification defaults.

        The format has two relevant zones:
        - field 1: legacy decimal profile, ending with currency.
        - field 2: CI, GG, BI, BAJA, IVA.
        - field 3: extended decimal profiles and currency repetitions.
        """
        data.raw_k = raw
        data.k_decimal_profile = self._field(fields, 1).strip()
        legacy = self._subfields(self._field(fields, 1), keep_empty=True)
        if legacy:
            # The legacy profile convention places currency in the 9th subfield.
            for value in reversed(legacy):
                value = (value or "").strip()
                if value and not re.fullmatch(r"[-+]?\d+(?:[\.,]\d+)?", value):
                    data.k_currency = value
                    break
        coeffs = self._subfields(self._field(fields, 2), keep_empty=True)
        if coeffs:
            data.k_ci = to_float(coeffs[0]) if len(coeffs) > 0 else 0.0
            data.k_gg = to_float(coeffs[1]) if len(coeffs) > 1 else 0.0
            data.k_bi = to_float(coeffs[2]) if len(coeffs) > 2 else 0.0
            data.k_baja = to_float(coeffs[3]) if len(coeffs) > 3 else 0.0
            data.k_iva = to_float(coeffs[4]) if len(coeffs) > 4 else 0.0
        extended = self._subfields(self._field(fields, 3), keep_empty=True)
        if extended:
            data.k_decimal_profile = self._field(fields, 3).strip()
            for value in reversed(extended):
                value = (value or "").strip()
                if value and not re.fullmatch(r"[-+]?\d+(?:[\.,]\d+)?", value):
                    data.k_currency = value
                    break

    def _parse_c(self, fields: List[str]) -> ParsedConcept:
        codes = self._subfields(self._field(fields, 1))
        prices = [to_float(value) for value in self._subfields(self._field(fields, 4))]
        return ParsedConcept(
            code=codes[0] if codes else "",
            aliases=codes[1:],
            unit=self._field(fields, 2).strip(),
            summary=self._field(fields, 3).strip(),
            prices=prices,
            price_dates=self._subfields(self._field(fields, 5)),
            concept_type=self._field(fields, 6).strip(),
        )

    def _parse_t(self, fields: List[str], data: ParsedBC3):
        code = self._field(fields, 1).strip()
        if not code:
            return
        concept = data.concepts.setdefault(code, ParsedConcept(code=code))
        concept.text = self._field(fields, 2)

    def _parse_x(self, fields: List[str], data: ParsedBC3):
        code = self._field(fields, 1).strip()
        if not code:
            return
        concept = data.concepts.setdefault(code, ParsedConcept(code=code))
        tokens = self._subfields(self._field(fields, 2), keep_empty=False)
        for i in range(0, len(tokens), 2):
            key = tokens[i]
            val = tokens[i + 1] if i + 1 < len(tokens) else ""
            if key:
                concept.technical[key] = val

    def _parse_g(self, fields: List[str], data: ParsedBC3):
        code = self._field(fields, 1).strip()
        if not code:
            return
        concept = data.concepts.setdefault(code, ParsedConcept(code=code))
        url_ext = self._field(fields, 3).strip()
        for filename in self._subfields(self._field(fields, 2)):
            concept.media_refs.append(ParsedMediaRef(code=code, filename=filename, source="G", type_code="13", url_ext=url_ext))

    def _parse_f(self, fields: List[str], data: ParsedBC3):
        code = self._field(fields, 1).strip()
        if not code:
            return
        concept = data.concepts.setdefault(code, ParsedConcept(code=code))
        url_ext = self._field(fields, 3).strip()
        tokens = self._subfields(self._field(fields, 2), keep_empty=False)
        i = 0
        while i < len(tokens):
            type_code = tokens[i] if i < len(tokens) else ""
            files_field = tokens[i + 1] if i + 1 < len(tokens) else ""
            description = tokens[i + 2] if i + 2 < len(tokens) else ""
            for filename in [x.strip() for x in files_field.split(";") if x.strip()]:
                concept.media_refs.append(
                    ParsedMediaRef(code=code, filename=filename, source="F", type_code=type_code, description=description, url_ext=url_ext)
                )
            i += 3

    def _parse_d(self, fields: List[str]) -> List[ParsedDecompositionLine]:
        parent_code = self._field(fields, 1).strip()
        payload = self._field(fields, 3).strip() or self._field(fields, 2).strip()
        tokens = self._subfields(payload, keep_empty=True)
        result = []
        sequence = 1
        i = 0
        while i < len(tokens):
            child = tokens[i].strip() if i < len(tokens) else ""
            if not child:
                i += 1
                continue
            factor = to_float(tokens[i + 1]) if i + 1 < len(tokens) and tokens[i + 1].strip() else 1.0
            performance = to_float(tokens[i + 2]) if i + 2 < len(tokens) and tokens[i + 2].strip() else 1.0
            percent_codes = tokens[i + 3].strip() if i + 3 < len(tokens) else ""
            result.append(ParsedDecompositionLine(parent_code, child, sequence, factor or 1.0, performance or 1.0, percent_codes))
            sequence += 1
            i += 4 if percent_codes and ";" in percent_codes else 3
        return result

    def _parse_m(self, fields: List[str]) -> ParsedMeasurement:
        parent_child = self._subfields(self._field(fields, 1), keep_empty=False)
        if len(parent_child) >= 2:
            parent_code, child_code = parent_child[0], parent_child[1]
        elif parent_child:
            parent_code, child_code = "", parent_child[0]
        else:
            parent_code, child_code = "", ""
        position_path = "/".join(self._subfields(self._field(fields, 2), keep_empty=False))
        total = to_float(self._field(fields, 3))
        label = self._field(fields, 5).strip()
        tokens = self._subfields(self._field(fields, 4), keep_empty=True)
        items = []
        for i in range(0, len(tokens), 6):
            group = tokens[i:i+6]
            if not any(str(x).strip() for x in group):
                continue
            line_type = group[0].strip() if len(group) > 0 else ""
            comment_raw = group[1].strip() if len(group) > 1 else ""
            comment, bim_id = self._split_bim(comment_raw)
            units = to_float(group[2]) if len(group) > 2 else 0.0
            length = to_float(group[3]) if len(group) > 3 else 0.0
            width = to_float(group[4]) if len(group) > 4 else 0.0
            height = to_float(group[5]) if len(group) > 5 else 0.0
            subtotal = self._calc_subtotal(line_type, comment, units, length, width, height)
            items.append(ParsedMeasurementItem(line_type, comment, bim_id, units, length, width, height, subtotal))
        return ParsedMeasurement(parent_code, child_code, position_path, total, label, items)

    def _split_bim(self, comment: str) -> Tuple[str, str]:
        if "#" not in comment:
            return comment, ""
        left, right = comment.rsplit("#", 1)
        return left.strip(), right.strip()

    def _calc_subtotal(self, line_type, comment, units, length, width, height):
        if line_type in ("1", "2"):
            return 0.0
        values = [value for value in (units, length, width, height) if value not in (0.0, None)]
        if not values:
            return 0.0
        subtotal = 1.0
        for value in values:
            subtotal *= value
        return subtotal

    def _field(self, fields: List[str], index: int) -> str:
        return sanitize_text(fields[index]) if len(fields) > index else ""

    def _subfields(self, value: str, keep_empty: bool = False) -> List[str]:
        parts = [sanitize_text(part).strip(" \t\r\n") for part in sanitize_text(value).split("\\")]
        if keep_empty:
            return parts
        return [part for part in parts if part != ""]

    def _first_subfield(self, value: str) -> str:
        items = self._subfields(value)
        return items[0] if items else ""
