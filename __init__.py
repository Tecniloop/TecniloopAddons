# -*- coding: utf-8 -*-
import base64
import datetime as dt
import decimal
import io
import json
import mimetypes
import posixpath
import re
import zipfile
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple


IMAGE_EXTENSIONS = {'.bmp', '.gif', '.jpg', '.jpeg', '.png', '.tif', '.tiff', '.webp'}
SUPPORTED_ATTACHMENT_EXTENSIONS = IMAGE_EXTENSIONS | {'.pdf', '.avi', '.ppt', '.pptx', '.rtf', '.htm', '.html', '.txt', '.csv'}
EXECUTABLE_EXTENSIONS = {'.exe', '.dll', '.bat', '.cmd', '.com', '.msi', '.ps1', '.sh'}



def sanitize_text(value):
    """Return a PostgreSQL-safe text value.

    Some BC3 files include NUL bytes/characters, especially when a source is
    generated with an unexpected encoding. PostgreSQL refuses text values that
    contain NUL (0x00), so remove them as early as possible and again before
    writing user-visible text to Odoo models.
    """
    if value is None:
        return ''
    if not isinstance(value, str):
        value = str(value)
    return value.replace('\x00', '')


def sanitize_value(value):
    if isinstance(value, str) or value is None:
        return sanitize_text(value)
    if isinstance(value, list):
        return [sanitize_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(sanitize_value(item) for item in value)
    if isinstance(value, dict):
        return {sanitize_text(key): sanitize_value(val) for key, val in value.items()}
    return value


@dataclass
class BC3AttachmentRef:
    code: str
    filename: str
    source: str
    type_code: str = ''
    description: str = ''
    url_ext: str = ''

    @property
    def extension(self) -> str:
        return posixpath.splitext(self.filename.lower())[1]

    @property
    def is_image(self) -> bool:
        return self.extension in IMAGE_EXTENSIONS


@dataclass
class BC3Concept:
    code: str
    aliases: List[str] = field(default_factory=list)
    unit: str = ''
    summary: str = ''
    prices: List[float] = field(default_factory=list)
    price_dates: List[str] = field(default_factory=list)
    concept_type: str = ''
    text: str = ''
    technical: Dict[str, str] = field(default_factory=dict)
    graphics: List[BC3AttachmentRef] = field(default_factory=list)
    attachments: List[BC3AttachmentRef] = field(default_factory=list)
    raw_c_record: str = ''

    def all_attachment_refs(self) -> List[BC3AttachmentRef]:
        return list(self.graphics) + list(self.attachments)


@dataclass
class BC3Data:
    bc3_filename: str
    encoding: str
    version: str = ''
    charset: str = ''
    program: str = ''
    property_file: str = ''
    comment: str = ''
    info_type: str = ''
    url_base: str = ''
    concepts: Dict[str, BC3Concept] = field(default_factory=dict)
    technical_dictionary: Dict[str, Dict[str, str]] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)

    def importable_concepts(self, include_type_4: bool = False, include_type_5: bool = False) -> List[BC3Concept]:
        result = []
        for concept in self.concepts.values():
            code = (concept.code or '').strip()
            if not code:
                continue
            # Root concepts and chapters use trailing ## or #. Commercial IDs may contain # in the middle.
            if code.endswith('#'):
                continue
            if concept.concept_type == '4' and not include_type_4:
                continue
            if concept.concept_type == '5' and not include_type_5:
                continue
            if concept.summary or concept.unit or concept.prices or concept.all_attachment_refs() or concept.text:
                result.append(concept)
        return result


class BC3ParseError(Exception):
    pass


class SafeZipBC3:
    def __init__(self, zip_bytes: bytes, max_members: int = 2000, max_total_size: int = 250 * 1024 * 1024, max_file_size: int = 75 * 1024 * 1024):
        self.zip_bytes = zip_bytes
        self.max_members = max_members
        self.max_total_size = max_total_size
        self.max_file_size = max_file_size
        self._zip = zipfile.ZipFile(io.BytesIO(zip_bytes))
        self._members = []
        self._by_path = {}
        self._by_basename = {}
        self._validate_and_index()

    def close(self):
        self._zip.close()

    def _normalize_member_name(self, name: str) -> str:
        if not name or '\x00' in name:
            raise BC3ParseError('Invalid file name in ZIP.')
        normalized = name.replace('\\', '/')
        if normalized.startswith('/') or re.match(r'^[A-Za-z]:', normalized):
            raise BC3ParseError('Absolute paths are not allowed in ZIP files.')
        normalized = posixpath.normpath(normalized)
        if normalized == '.' or normalized.startswith('../') or normalized == '..':
            raise BC3ParseError('Path traversal is not allowed in ZIP files.')
        return normalized

    def _validate_and_index(self):
        infos = self._zip.infolist()
        if len(infos) > self.max_members:
            raise BC3ParseError('ZIP has too many files.')
        total_size = 0
        for info in infos:
            if info.is_dir():
                continue
            normalized = self._normalize_member_name(info.filename)
            total_size += info.file_size
            if info.file_size > self.max_file_size:
                raise BC3ParseError('ZIP contains a file larger than the allowed limit: %s' % normalized)
            if total_size > self.max_total_size:
                raise BC3ParseError('ZIP uncompressed size is larger than the allowed limit.')
            self._members.append((normalized, info))
            self._by_path.setdefault(normalized.lower(), info)
            self._by_basename.setdefault(posixpath.basename(normalized).lower(), info)

    def list_bc3(self) -> List[str]:
        return [name for name, info in self._members if name.lower().endswith('.bc3')]

    def read_bc3(self, bc3_name: Optional[str] = None) -> Tuple[str, bytes]:
        bc3_files = self.list_bc3()
        if not bc3_files:
            raise BC3ParseError('No BC3 file was found inside the ZIP.')
        selected = bc3_name or bc3_files[0]
        info = self._by_path.get(selected.lower()) or self._by_basename.get(posixpath.basename(selected).lower())
        if not info:
            raise BC3ParseError('Selected BC3 file was not found: %s' % selected)
        return self._normalize_member_name(info.filename), self._zip.read(info)

    def read_related_file(self, filename: str) -> Tuple[Optional[str], Optional[bytes]]:
        if not filename:
            return None, None
        candidate = filename.strip().replace('\\', '/')
        candidate = candidate.lstrip('./')
        key = posixpath.normpath(candidate).lower()
        base_key = posixpath.basename(candidate).lower()
        info = self._by_path.get(key) or self._by_basename.get(base_key)
        if not info:
            return None, None
        normalized = self._normalize_member_name(info.filename)
        ext = posixpath.splitext(normalized.lower())[1]
        if ext in EXECUTABLE_EXTENSIONS:
            return normalized, None
        return normalized, self._zip.read(info)


class BC3Parser:
    ENCODING_MAP = {
        'ANSI': 'cp1252',
        '850': 'cp850',
        '437': 'cp437',
    }

    def parse(self, bc3_bytes: bytes, bc3_filename: str = '') -> BC3Data:
        raw = bc3_bytes.rstrip(b'\x1a')
        encoding, charset = self._detect_encoding(raw)
        text = sanitize_text(raw.decode(encoding, errors='replace'))
        data = BC3Data(bc3_filename=bc3_filename, encoding=encoding, charset=charset)
        for record_type, fields, raw_record in self._iter_records(text):
            try:
                if record_type == 'V':
                    self._parse_v(fields, data)
                elif record_type == 'C':
                    concept = self._parse_c(fields, raw_record)
                    if concept and concept.code:
                        existing = data.concepts.get(concept.code)
                        if existing:
                            data.warnings.append('Duplicate concept %s replaced by a later ~C record.' % concept.code)
                        data.concepts[concept.code] = concept
                elif record_type == 'T':
                    self._parse_t(fields, data)
                elif record_type == 'X':
                    self._parse_x(fields, data)
                elif record_type == 'G':
                    self._parse_g(fields, data)
                elif record_type == 'F':
                    self._parse_f(fields, data)
            except Exception as exc:
                data.warnings.append('Cannot parse ~%s record: %s' % (record_type, exc))
        return data

    def _detect_encoding(self, raw: bytes) -> Tuple[str, str]:
        probe = sanitize_text(raw.decode('latin1', errors='ignore'))
        charset = ''
        for record_type, fields, raw_record in self._iter_records(probe):
            if record_type == 'V':
                if len(fields) > 5:
                    charset = fields[5].strip().upper()
                break
        return self.ENCODING_MAP.get(charset, 'cp850'), charset or '850'

    def _iter_records(self, text: str) -> Iterable[Tuple[str, List[str], str]]:
        for chunk in text.split('~'):
            chunk = sanitize_text(chunk).lstrip('\ufeff \t\r\n')
            if not chunk:
                continue
            raw_record = chunk
            fields = chunk.split('|')
            if not fields:
                continue
            header = fields[0].strip().upper()
            if not header:
                continue
            record_type = header[0]
            yield record_type, fields, raw_record

    def _parse_v(self, fields: List[str], data: BC3Data):
        data.property_file = self._field(fields, 1).strip()
        data.version = self._first_subfield(self._field(fields, 2))
        data.program = self._field(fields, 3).strip()
        data.charset = self._field(fields, 5).strip() or data.charset
        data.comment = self._field(fields, 6).strip()
        data.info_type = self._field(fields, 7).strip()
        data.url_base = self._field(fields, 10).strip()

    def _parse_c(self, fields: List[str], raw_record: str) -> Optional[BC3Concept]:
        codes = self._subfields(self._field(fields, 1))
        if not codes:
            return None
        code = codes[0]
        prices = [self._to_float(p) for p in self._subfields(self._field(fields, 4))]
        prices = [p for p in prices if p is not None]
        return BC3Concept(
            code=code,
            aliases=codes[1:],
            unit=self._field(fields, 2).strip(),
            summary=self._field(fields, 3).strip(),
            prices=prices,
            price_dates=self._subfields(self._field(fields, 5)),
            concept_type=self._field(fields, 6).strip(),
            raw_c_record=raw_record,
        )

    def _parse_t(self, fields: List[str], data: BC3Data):
        code = self._field(fields, 1).strip()
        if not code:
            return
        concept = data.concepts.setdefault(code, BC3Concept(code=code))
        concept.text = self._field(fields, 2)

    def _parse_x(self, fields: List[str], data: BC3Data):
        code = self._field(fields, 1).strip()
        tokens = self._subfields(self._field(fields, 2), keep_empty=False)
        if not code:
            dictionary = {}
            i = 0
            while i < len(tokens):
                key = tokens[i]
                description = tokens[i + 1] if i + 1 < len(tokens) else ''
                unit = tokens[i + 2] if i + 2 < len(tokens) else ''
                if key:
                    dictionary[key] = {'description': description, 'unit': unit}
                i += 3
            data.technical_dictionary.update(dictionary)
            return
        concept = data.concepts.setdefault(code, BC3Concept(code=code))
        i = 0
        while i < len(tokens):
            key = tokens[i]
            value = tokens[i + 1] if i + 1 < len(tokens) else ''
            if key:
                concept.technical[key] = value
            i += 2

    def _parse_g(self, fields: List[str], data: BC3Data):
        code = self._field(fields, 1).strip()
        if not code:
            return
        concept = data.concepts.setdefault(code, BC3Concept(code=code))
        url_ext = self._field(fields, 3).strip()
        for filename in self._subfields(self._field(fields, 2)):
            concept.graphics.append(BC3AttachmentRef(code=code, filename=filename, source='G', type_code='13', url_ext=url_ext))

    def _parse_f(self, fields: List[str], data: BC3Data):
        code = self._field(fields, 1).strip()
        if not code:
            return
        concept = data.concepts.setdefault(code, BC3Concept(code=code))
        url_ext = self._field(fields, 3).strip()
        tokens = self._subfields(self._field(fields, 2), keep_empty=False)
        i = 0
        while i < len(tokens):
            type_code = tokens[i] if i < len(tokens) else ''
            files_field = tokens[i + 1] if i + 1 < len(tokens) else ''
            description = tokens[i + 2] if i + 2 < len(tokens) else ''
            for filename in [x.strip() for x in files_field.split(';') if x.strip()]:
                concept.attachments.append(BC3AttachmentRef(
                    code=code,
                    filename=filename,
                    source='F',
                    type_code=type_code,
                    description=description,
                    url_ext=url_ext,
                ))
            i += 3

    def _field(self, fields: List[str], index: int) -> str:
        return sanitize_text(fields[index]) if len(fields) > index else ''

    def _subfields(self, value: str, keep_empty: bool = False) -> List[str]:
        parts = [sanitize_text(part).strip(' \t\r\n') for part in sanitize_text(value).split('\\')]
        if keep_empty:
            return parts
        return [part for part in parts if part != '']

    def _first_subfield(self, value: str) -> str:
        items = self._subfields(value)
        return items[0] if items else ''

    def _to_float(self, value: str) -> Optional[float]:
        value = (value or '').strip()
        if not value:
            return None
        if ',' in value and '.' not in value:
            value = value.replace(',', '.')
        try:
            return float(decimal.Decimal(value))
        except decimal.InvalidOperation:
            return None


def parse_bc3_date(value: str) -> Optional[dt.date]:
    value = re.sub(r'\D', '', value or '')
    if not value:
        return None
    if len(value) % 2 == 1:
        value = '0' + value
    try:
        if len(value) <= 2:
            yy = int(value)
            year = 1900 + yy if yy >= 80 else 2000 + yy
            return dt.date(year, 1, 1)
        if len(value) <= 4:
            mm = int(value[:-2] or '1') or 1
            yy = int(value[-2:])
            year = 1900 + yy if yy >= 80 else 2000 + yy
            return dt.date(year, mm, 1)
        if len(value) <= 6:
            dd = int(value[0:2]) or 1
            mm = int(value[2:4]) or 1
            yy = int(value[4:6])
            year = 1900 + yy if yy >= 80 else 2000 + yy
            return dt.date(year, mm, dd)
        dd = int(value[0:2]) or 1
        mm = int(value[2:4]) or 1
        year = int(value[4:8])
        return dt.date(year, mm, dd)
    except ValueError:
        return None


def json_dumps(value) -> str:
    return json.dumps(sanitize_value(value), ensure_ascii=False, sort_keys=True, indent=2)


def guess_mimetype(filename: str) -> str:
    mimetype, _enc = mimetypes.guess_type(filename or '')
    return mimetype or 'application/octet-stream'


def b64(data: bytes) -> bytes:
    return base64.b64encode(data or b'')
