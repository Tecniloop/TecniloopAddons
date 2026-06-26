import base64
import ipaddress
import io
import os
import posixpath
import zipfile
import socket
import ssl
import urllib.error
import urllib.parse
import urllib.request

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .bc3_parser import BC3Parser, BC3ParseError

try:
    import certifi
except ImportError:  # pragma: no cover - optional runtime dependency
    certifi = None


class Bc3File(models.Model):
    _name = "bc3.file"
    _description = "BC3 File"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"

    name = fields.Char(required=True, tracking=True)
    source_type = fields.Selection(
        [("upload", "Uploaded File"), ("url", "URL"), ("server_path", "Server Path")],
        string="Source Type",
        default="upload",
        required=True,
        tracking=True,
    )
    data_file = fields.Binary(string="BC3 File", attachment=True)
    filename = fields.Char()
    source_url = fields.Char(string="Source URL", tracking=True)
    server_path = fields.Char(
        string="Server File Path",
        help="Absolute path on the Odoo server. Use it for very large files to avoid browser/proxy upload limits.",
        tracking=True,
    )
    allow_insecure_ssl = fields.Boolean(
        string="Allow Insecure SSL",
        help="Use only for trusted catalog URLs with broken certificate chains.",
    )
    max_download_size_mb = fields.Integer(
        string="Max URL Download Size (MB)",
        default=0,
        help="0 means no explicit module limit. Server memory and timeout limits still apply.",
    )
    state = fields.Selection(
        [("draft", "Draft"), ("parsed", "Parsed"), ("error", "Error")],
        default="draft",
        required=True,
        tracking=True,
    )
    error_message = fields.Text(readonly=True)
    warning_message = fields.Text(readonly=True)
    property_file = fields.Char(readonly=True)
    version = fields.Char(readonly=True)
    program = fields.Char(readonly=True)
    charset = fields.Char(readonly=True)
    encoding = fields.Char(readonly=True)
    comment = fields.Char(readonly=True)
    info_type = fields.Selection(
        [("1", "Database"), ("2", "Budget"), ("3", "Certification"), ("4", "Database update"), ("", "Unknown")],
        string="Information Type",
        readonly=True,
    )
    certification_number = fields.Char(readonly=True)
    certification_date = fields.Date(readonly=True)
    url_base = fields.Char(readonly=True)
    raw_k = fields.Text(string="Raw ~K", readonly=True)
    record_count = fields.Integer(readonly=True)
    concept_count = fields.Integer(readonly=True)
    decomposition_count = fields.Integer(readonly=True)
    measurement_count = fields.Integer(readonly=True)
    raw_record_ids = fields.One2many("bc3.raw.record", "file_id", string="Raw Records")
    concept_ids = fields.One2many("bc3.concept", "file_id", string="Concepts")
    decomposition_line_ids = fields.One2many("bc3.decomposition.line", "file_id", string="Decompositions")
    measurement_line_ids = fields.One2many("bc3.measurement.line", "file_id", string="Measurements")
    media_ref_ids = fields.One2many("bc3.concept.media", "file_id", string="Media References")

    def action_parse(self):
        for rec in self:
            rec._parse_file()
        return True

    def _parse_file(self):
        self.ensure_one()
        self.raw_record_ids.unlink()
        self.concept_ids.unlink()
        self.decomposition_line_ids.unlink()
        self.measurement_line_ids.unlink()
        payload, effective_filename = self._read_source_payload()
        try:
            parsed = BC3Parser().parse(payload, effective_filename or self.filename or self.name)
        except BC3ParseError as exc:
            self.write({"state": "error", "error_message": str(exc)})
            raise UserError(str(exc)) from exc
        concept_by_code = {}
        Concept = self.env["bc3.concept"]

        def _register_concept_key(key, concept_rec):
            key = (key or "").strip()
            if not key:
                return
            concept_by_code.setdefault(key, concept_rec)
            normalized = Concept._normalize_code(key)
            if normalized:
                concept_by_code.setdefault(normalized, concept_rec)

        raw_vals = [
            {
                "file_id": self.id,
                "sequence": item.sequence,
                "record_type": item.record_type,
                "raw_text": item.raw,
            }
            for item in parsed.records
        ]
        if raw_vals:
            self.env["bc3.raw.record"].create(raw_vals)
        concept_count = 0
        for concept in {id(c): c for c in parsed.concepts.values()}.values():
            concept_count += 1
            code = concept.code
            concept_rec = self.env["bc3.concept"].create({
                "file_id": self.id,
                "code": code,
                "normalized_code": self.env["bc3.concept"]._normalize_code(code),
                "name": concept.summary or code,
                "unit_name": concept.unit,
                "concept_type": concept.concept_type,
                "category": self.env["bc3.concept"]._get_category_from_code(code, concept.concept_type),
                "price_unit": concept.prices[0] if concept.prices else 0.0,
                "price_date_raw": concept.price_dates[0] if concept.price_dates else "",
                "text": concept.text,
                "technical_json": str(concept.technical or {}),
            })
            _register_concept_key(code, concept_rec)
            media_vals = []
            for seq, media in enumerate(concept.media_refs or [], start=1):
                media_vals.append({
                    "concept_id": concept_rec.id,
                    "sequence": seq,
                    "source": media.source if media.source in ("G", "F") else "G",
                    "filename": media.filename,
                    "type_code": media.type_code,
                    "description": media.description,
                    "url_ext": media.url_ext,
                    "is_image": media.is_image,
                })
            if media_vals:
                self.env["bc3.concept.media"].create(media_vals)
            for alias in concept.aliases:
                self.env["bc3.concept.code"].create({
                    "concept_id": concept_rec.id,
                    "name": alias,
                    "normalized_code": Concept._normalize_code(alias),
                })
                _register_concept_key(alias, concept_rec)
        decomp_vals = []
        for line in parsed.decomposition_lines:
            parent = concept_by_code.get((line.parent_code or "").strip()) or concept_by_code.get(Concept._normalize_code(line.parent_code))
            child = concept_by_code.get((line.child_code or "").strip()) or concept_by_code.get(Concept._normalize_code(line.child_code))
            decomp_vals.append({
                "file_id": self.id,
                "parent_code": line.parent_code,
                "child_code": line.child_code,
                "parent_concept_id": parent.id if parent else False,
                "child_concept_id": child.id if child else False,
                "sequence": line.sequence,
                "factor": line.factor,
                "performance": line.performance,
                "percent_codes": line.percent_codes,
            })
        if decomp_vals:
            self.env["bc3.decomposition.line"].create(decomp_vals)
        measurement_vals = []
        for measurement in parsed.measurements:
            parent = concept_by_code.get((measurement.parent_code or "").strip()) or concept_by_code.get(Concept._normalize_code(measurement.parent_code))
            child = concept_by_code.get((measurement.child_code or "").strip()) or concept_by_code.get(Concept._normalize_code(measurement.child_code))
            if measurement.items:
                for idx, item in enumerate(measurement.items, start=1):
                    measurement_vals.append(self._measurement_vals(measurement, item, idx, parent, child))
            else:
                measurement_vals.append(self._measurement_vals(measurement, None, 1, parent, child))
        if measurement_vals:
            self.env["bc3.measurement.line"].create(measurement_vals)
        vals = {
            "state": "parsed",
            "error_message": False,
            "warning_message": "\n".join(parsed.warnings),
            "property_file": parsed.property_file,
            "version": parsed.version,
            "program": parsed.program,
            "charset": parsed.charset,
            "encoding": parsed.encoding,
            "comment": parsed.comment,
            "info_type": parsed.info_type if parsed.info_type in ("1", "2", "3", "4") else "",
            "certification_number": parsed.certification_number,
            "certification_date": parsed.certification_date,
            "url_base": parsed.url_base,
            "raw_k": parsed.raw_k,
            "record_count": len(parsed.records),
            "concept_count": concept_count,
            "decomposition_count": len(parsed.decomposition_lines),
            "measurement_count": len(measurement_vals),
        }
        if effective_filename and not self.filename:
            vals["filename"] = effective_filename
        self.write(vals)

    def _read_source_payload(self):
        self.ensure_one()
        if self.source_type == "url":
            payload, downloaded_filename = self._download_url(self.source_url)
            return self._extract_bc3_payload(payload, downloaded_filename)
        if self.source_type == "server_path":
            payload, path_filename = self._read_server_path(self.server_path)
            return self._extract_bc3_payload(payload, path_filename)
        if not self.data_file:
            raise UserError(_("Please upload a BC3 file first."))
        return self._extract_bc3_payload(base64.b64decode(self.data_file), self.filename or self.name)


    def _extract_bc3_payload(self, payload, source_filename):
        payload = payload or b""
        source_filename = source_filename or self.filename or self.name
        selected_name = (self.filename or "").strip()
        if not payload:
            raise UserError(_("The BC3 source is empty."))
        try:
            is_zip = zipfile.is_zipfile(io.BytesIO(payload))
        except Exception:
            is_zip = False
        if not is_zip:
            return payload, selected_name or source_filename
        try:
            archive = zipfile.ZipFile(io.BytesIO(payload))
        except zipfile.BadZipFile as exc:
            raise UserError(_("Invalid ZIP file: %s") % exc)
        candidates = [info for info in archive.infolist() if not info.is_dir() and info.filename.lower().endswith(".bc3")]
        if selected_name and selected_name.lower().endswith(".bc3"):
            normalized_selected = selected_name.replace("\\", "/").lower()
            selected = [info for info in candidates if info.filename.replace("\\", "/").lower() == normalized_selected or posixpath.basename(info.filename).lower() == posixpath.basename(normalized_selected)]
            if selected:
                candidates = selected
        if not candidates:
            raise UserError(_("The ZIP file does not contain any .bc3 file."))
        info = candidates[0]
        if info.file_size > 0 and self.max_download_size_mb and info.file_size > int(self.max_download_size_mb) * 1024 * 1024:
            raise UserError(_("The BC3 file inside the ZIP is larger than the configured limit."))
        return archive.read(info), posixpath.basename(info.filename)

    def _read_server_path(self, path):
        path = (path or "").strip()
        if not path:
            raise UserError(_("Please set a server file path."))
        if not os.path.isabs(path):
            raise UserError(_("The server file path must be absolute."))
        if not os.path.isfile(path):
            raise UserError(_("The server file path does not exist or is not a file: %s") % path)
        with open(path, "rb") as handler:
            payload = handler.read()
        if not payload:
            raise UserError(_("The server file is empty."))
        return payload, os.path.basename(path)

    def _has_control_chars(self, value):
        return any(ord(ch) < 32 or ord(ch) == 127 for ch in value or "")

    def _validate_download_url(self, url):
        if self._has_control_chars(url):
            raise UserError(_("URL cannot contain control characters."))
        parsed = urllib.parse.urlparse(url or "")
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise UserError(_("Only HTTP/HTTPS URLs are allowed."))
        hostname = parsed.hostname
        if not hostname:
            raise UserError(_("The URL does not contain a valid host."))
        try:
            for addr_info in socket.getaddrinfo(hostname, None):
                ip = ipaddress.ip_address(addr_info[4][0])
                if ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_private or ip.is_reserved:
                    raise UserError(_("The URL host resolves to a private or reserved address and was blocked."))
        except UserError:
            raise
        except Exception as exc:
            raise UserError(_("Cannot resolve URL host: %s") % exc)
        return parsed

    def _get_ssl_context(self):
        if self.allow_insecure_ssl:
            return ssl._create_unverified_context()
        if certifi:
            return ssl.create_default_context(cafile=certifi.where())
        return ssl.create_default_context()

    def _download_url(self, url, required=True, max_size=None):
        if max_size is None and self.max_download_size_mb:
            max_size = int(self.max_download_size_mb) * 1024 * 1024
        parsed = urllib.parse.urlparse(url or "")
        filename = posixpath.basename(urllib.parse.unquote(parsed.path)) or "download.bc3"
        try:
            parsed = self._validate_download_url(url)
            filename = posixpath.basename(urllib.parse.unquote(parsed.path)) or filename
            request = urllib.request.Request(url, headers={"User-Agent": "Odoo-BC3-Importer/1.0"})
            with urllib.request.urlopen(request, timeout=60, context=self._get_ssl_context()) as response:
                final_url = response.geturl()
                final_parsed = self._validate_download_url(final_url)
                filename = posixpath.basename(urllib.parse.unquote(final_parsed.path)) or filename
                content_length = response.headers.get("Content-Length")
                if max_size and content_length and int(content_length) > max_size:
                    raise UserError(_("The remote file is larger than the configured limit."))
                chunks = []
                total = 0
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if max_size and total > max_size:
                        raise UserError(_("The remote file is larger than the configured limit."))
                    chunks.append(chunk)
                payload = b"".join(chunks)
                if not payload and required:
                    raise UserError(_("The downloaded file is empty."))
                return payload, filename
        except UserError:
            if required:
                raise
            return None, filename
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, ssl.SSLError, ValueError) as exc:
            if required:
                raise UserError(_("Cannot download URL %s: %s") % (url, exc))
            return None, filename

    def _measurement_vals(self, measurement, item, idx, parent, child):
        vals = {
            "file_id": self.id,
            "parent_code": measurement.parent_code,
            "child_code": measurement.child_code,
            "parent_concept_id": parent.id if parent else False,
            "child_concept_id": child.id if child else False,
            "position_path": measurement.position_path,
            "measurement_total": measurement.measurement_total,
            "sequence": idx,
            "label": measurement.label,
        }
        if item:
            vals.update({
                "line_type": item.line_type,
                "comment": item.comment,
                "bim_id": item.bim_id,
                "units": item.units,
                "length": item.length,
                "width": item.width,
                "height": item.height,
                "subtotal": item.subtotal,
            })
        return vals


class Bc3RawRecord(models.Model):
    _name = "bc3.raw.record"
    _description = "BC3 Raw Record"
    _order = "file_id, sequence"

    file_id = fields.Many2one("bc3.file", required=True, ondelete="cascade", index=True)
    sequence = fields.Integer(required=True)
    record_type = fields.Char(required=True, index=True)
    raw_text = fields.Text(required=True)
