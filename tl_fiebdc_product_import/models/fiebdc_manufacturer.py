# -*- coding: utf-8 -*-
import base64
import html
import io
import json
import ipaddress
import posixpath
import socket
import ssl
import zipfile
import urllib.error
import urllib.parse
import urllib.request

from odoo import _, fields, models
from odoo.exceptions import UserError

try:
    import certifi
except ImportError:  # pragma: no cover - optional runtime dependency
    certifi = None

from .fiebdc_parser import (
    BC3ParseError,
    BC3Parser,
    BC3Data,
    BC3Concept,
    BC3AttachmentRef,
    SafeZipBC3,
    SafeRarBC3,
    EXECUTABLE_EXTENSIONS,
    b64,
    guess_mimetype,
    json_dumps,
    parse_bc3_date,
    sanitize_text,
    sanitize_value,
)


class FiebdcUrlResourceHandler:
    """Read BC3-related resources from HTTP/HTTPS URLs.

    The existing wizard reads related images/PDFs from a ZIP. Manufacturer imports
    start from a persisted BC3 URL, so related files are resolved from the BC3
    file location, from the BC3 ~V URL base, and from ~G/~F URL extensions.
    """

    def __init__(self, manufacturer, data):
        self.manufacturer = manufacturer
        self.data = data

    def _has_control_chars(self, value):
        return any(ord(ch) < 32 or ord(ch) == 127 for ch in sanitize_text(value))

    def _is_safe_reference(self, value):
        value = sanitize_text(value).strip()
        if not value or self._has_control_chars(value):
            return False
        return True

    def _as_directory_url(self, url):
        if not url:
            return ''
        parsed = urllib.parse.urlparse(url)
        if not parsed.scheme:
            return ''
        if url.endswith('/'):
            return url
        path = parsed.path or '/'
        if posixpath.basename(path) and '.' in posixpath.basename(path):
            path = posixpath.dirname(path.rstrip('/')) + '/'
        elif not path.endswith('/'):
            path += '/'
        return urllib.parse.urlunparse(parsed._replace(path=path, params='', query='', fragment=''))

    def _candidate_urls(self, ref):
        filename = sanitize_text(ref.filename or '').strip().replace('\\', '/')
        if not self._is_safe_reference(filename):
            return []
        parsed_filename = urllib.parse.urlparse(filename)
        if parsed_filename.scheme in ('http', 'https'):
            return [filename] if self._is_safe_reference(filename) else []

        candidates = []
        source_dir = self._as_directory_url(self.manufacturer.bc3_url)
        data_base = self._as_directory_url(self.data.url_base)
        ref_ext = sanitize_text(ref.url_ext or '').strip().replace('\\', '/')
        if ref_ext and not self._is_safe_reference(ref_ext):
            ref_ext = ''
        ref_ext_parsed = urllib.parse.urlparse(ref_ext)

        if ref_ext:
            if ref_ext_parsed.scheme in ('http', 'https'):
                candidates.append(urllib.parse.urljoin(self._as_directory_url(ref_ext), filename))
            else:
                for base in [data_base, source_dir]:
                    if base:
                        candidates.append(urllib.parse.urljoin(urllib.parse.urljoin(base, ref_ext.rstrip('/') + '/'), filename))

        for base in [data_base, source_dir]:
            if base:
                candidates.append(urllib.parse.urljoin(base, filename.lstrip('/')))

        # Keep order while removing duplicates and discard invalid/control-character URLs.
        seen = set()
        result = []
        for url in candidates:
            if url and url not in seen and self._is_safe_reference(url):
                result.append(url)
                seen.add(url)
        return result

    def read_related_file(self, ref):
        for url in self._candidate_urls(ref):
            parsed = urllib.parse.urlparse(url)
            normalized_name = sanitize_text(posixpath.basename(urllib.parse.unquote(parsed.path)) or posixpath.basename(sanitize_text(ref.filename)))
            ext = posixpath.splitext(normalized_name.lower())[1]
            if ext in EXECUTABLE_EXTENSIONS:
                return normalized_name, None
            payload = self.manufacturer._download_url(
                url,
                required=False,
                max_size=self.manufacturer._download_limit_bytes(
                    self.manufacturer.max_related_file_size_mb,
                    default_mb=75,
                ),
            )[1]
            if payload:
                return normalized_name, payload
        return None, None


class FiebdcZipUrlResourceHandler:
    """Read related files first from the downloaded archive and then from URLs."""

    def __init__(self, manufacturer, data, zip_handler):
        self.zip_handler = zip_handler
        self.url_handler = FiebdcUrlResourceHandler(manufacturer, data)

    def read_related_file(self, ref):
        normalized_name, payload = self.zip_handler.read_related_file(sanitize_text(ref.filename))
        if normalized_name:
            return sanitize_text(normalized_name), payload
        return self.url_handler.read_related_file(ref)


class FiebdcManufacturer(models.Model):
    _name = 'fiebdc.manufacturer'
    _description = 'FIEBDC Manufacturer'
    _inherit = ['mail.thread']
    _order = 'name'

    name = fields.Char(string='Fabricante', required=True, tracking=True)
    active = fields.Boolean(default=True)
    bc3_url = fields.Char(
        string='URL del fichero BC3/ZIP/RAR',
        required=True,
        tracking=True,
        help='URL HTTP/HTTPS desde la que se descargara el fichero BC3, ZIP o RAR del fabricante.',
    )
    bc3_filename = fields.Char(
        string='Nombre del BC3',
        help='Opcional. Si se deja vacio se usara el nombre del fichero descargado.',
    )
    allow_insecure_ssl = fields.Boolean(
        string='Permitir SSL sin verificar',
        tracking=True,
        help=(
            'Active esta opcion solo para fabricantes conocidos cuyo servidor HTTPS tenga '
            'una cadena de certificados incompleta o no verificable. La descarga se '
            'intentara primero con certificados CA fiables; si marca esta opcion se '
            'desactiva la verificacion SSL para esta URL y sus adjuntos relacionados.'
        ),
    )
    max_bc3_download_size_mb = fields.Integer(
        string='Limite descarga BC3 (MB)',
        default=500,
        required=True,
        help=(
            'Tamano maximo permitido para descargar el fichero principal desde la URL. '
            'Aumente este valor solo para fabricantes de confianza con catalogos grandes.'
        ),
    )
    max_related_file_size_mb = fields.Integer(
        string='Limite adjunto relacionado (MB)',
        default=75,
        required=True,
        help=(
            'Tamano maximo permitido para cada imagen, PDF o documento relacionado '
            'referenciado por el BC3.'
        ),
    )

    update_existing = fields.Boolean(string='Update Existing Products', default=True)
    default_product_type = fields.Selection([
        ('consu', 'Goods'),
        ('service', 'Service'),
    ], default='consu', required=True)
    track_inventory = fields.Boolean(
        string='Track Inventory for Goods',
        default=True,
        help='Odoo 19 uses Product Type = Goods plus Track Inventory for stock-tracked articles.',
    )
    import_type_4 = fields.Boolean(string='Import BC3 Type 4')
    import_type_5 = fields.Boolean(string='Import BC3 Type 5')
    import_attachments = fields.Boolean(string='Import PDF/Documents', default=True)
    import_images = fields.Boolean(string='Import Images', default=True)
    set_first_image = fields.Boolean(string='Use First Image as Product Image', default=True)
    overwrite_image = fields.Boolean(string='Overwrite Existing Product Image')
    skip_duplicate_attachments = fields.Boolean(string='Skip Duplicate Attachments', default=True)
    dry_run = fields.Boolean(string='Preview Only', default=False)
    import_batch_size = fields.Integer(
        string='Registros por lote',
        default=200,
        required=True,
        help='Numero de productos que se procesan en cada lote para evitar timeouts con catalogos grandes.',
    )

    preview_html = fields.Html(string='Preview', readonly=True)
    last_import_batch_id = fields.Many2one('fiebdc.import.batch', string='Ultima importacion', readonly=True, copy=False)
    last_import_date = fields.Datetime(string='Fecha ultima importacion', readonly=True, copy=False)

    def action_preview(self):
        self.ensure_one()
        data, _resource_handler = self._parse_bc3_url()
        importable = data.importable_concepts(self.import_type_4, self.import_type_5)
        rows = []
        for concept in importable[:50]:
            rows.append('<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>' % (
                html.escape(sanitize_text(concept.code)),
                html.escape(sanitize_text(concept.unit)),
                html.escape(sanitize_text(concept.summary)),
                html.escape(str(concept.prices[0]) if concept.prices else ''),
                html.escape(str(len(concept.all_attachment_refs()))),
            ))
        warning_rows = ''.join('<li>%s</li>' % html.escape(sanitize_text(w)) for w in data.warnings[:20])
        self.preview_html = '''
            <p><b>BC3:</b> %s<br/>
            <b>URL:</b> %s<br/>
            <b>Encoding:</b> %s<br/>
            <b>Total concepts:</b> %s<br/>
            <b>Importable concepts:</b> %s</p>
            <table class="table table-sm table-hover">
              <thead><tr><th>Code</th><th>Unit</th><th>Name</th><th>Price</th><th>Files</th></tr></thead>
              <tbody>%s</tbody>
            </table>
            %s
        ''' % (
            html.escape(sanitize_text(data.bc3_filename)),
            html.escape(sanitize_text(self.bc3_url)),
            html.escape(sanitize_text(data.encoding)),
            len(data.concepts),
            len(importable),
            ''.join(rows) or '<tr><td colspan="5">No importable concepts found.</td></tr>',
            '<ul>%s</ul>' % warning_rows if warning_rows else '',
        )
        return self._reload_form()

    def action_import(self):
        self.ensure_one()
        data, _resource_handler, source_filename, source_payload = self._load_bc3_url()
        importable = data.importable_concepts(self.import_type_4, self.import_type_5)
        batch_size = max(int(self.import_batch_size or 200), 1)
        batch = self.env['fiebdc.import.batch'].sudo().create({
            'name': sanitize_text('%s - %s' % (self.name, data.bc3_filename or 'FIEBDC Import')),
            'manufacturer_id': self.id,
            'bc3_url': sanitize_text(self.bc3_url),
            'bc3_url_base': sanitize_text(data.url_base),
            'zip_filename': sanitize_text(source_filename),
            'bc3_filename': sanitize_text(data.bc3_filename),
            'bc3_encoding': sanitize_text(data.encoding),
            'total_concepts': len(data.concepts),
            'importable_concepts': len(importable),
            'batch_size': batch_size,
            'warning_count': len(data.warnings),
            'state': 'done' if self.dry_run or not importable else 'queued',
        })
        for warning in data.warnings:
            self._log(batch, 'warning', '', warning)
        if self.dry_run:
            batch.write({'finished_at': fields.Datetime.now()})
            self.write({'last_import_batch_id': batch.id, 'last_import_date': fields.Datetime.now()})
            return self._open_batch(batch)
        self._save_batch_source_attachment(batch, source_filename, source_payload)
        self._stage_import_lines(batch, importable)
        self.write({'last_import_batch_id': batch.id, 'last_import_date': fields.Datetime.now()})
        if importable:
            self._process_import_batch(batch, limit=batch_size)
        return self._open_batch(batch)

    def action_open_last_import_batch(self):
        self.ensure_one()
        if not self.last_import_batch_id:
            raise UserError(_('This manufacturer has no imports yet.'))
        return self._open_batch(self.last_import_batch_id)

    def _has_control_chars(self, value):
        return any(ord(ch) < 32 or ord(ch) == 127 for ch in sanitize_text(value))

    def _validate_download_url(self, url):
        if self._has_control_chars(url):
            raise UserError(_('URL cannot contain control characters.'))
        parsed = urllib.parse.urlparse(url or '')
        if parsed.scheme not in ('http', 'https') or not parsed.netloc:
            raise UserError(_('Only HTTP/HTTPS URLs are allowed.'))
        hostname = parsed.hostname
        if not hostname:
            raise UserError(_('The URL does not contain a valid host.'))
        try:
            for addr_info in socket.getaddrinfo(hostname, None):
                ip = ipaddress.ip_address(addr_info[4][0])
                if ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_private or ip.is_reserved:
                    raise UserError(_('The URL host resolves to a private or reserved address and was blocked.'))
        except UserError:
            raise
        except Exception as exc:
            raise UserError(_('Cannot resolve URL host: %s') % exc)
        return parsed

    def _get_ssl_context(self):
        if self.allow_insecure_ssl:
            return ssl._create_unverified_context()
        if certifi:
            return ssl.create_default_context(cafile=certifi.where())
        return ssl.create_default_context()

    def _is_ssl_certificate_error(self, exc):
        text = str(exc).lower()
        return (
            isinstance(exc, ssl.SSLError)
            or 'certificate_verify_failed' in text
            or ('certificate' in text and ('verify' in text or 'issuer' in text))
        )

    def _download_limit_bytes(self, size_mb, default_mb=500):
        try:
            size_mb = int(size_mb or 0)
        except (TypeError, ValueError):
            size_mb = 0
        if size_mb <= 0:
            size_mb = default_mb
        return size_mb * 1024 * 1024

    def _download_limit_label(self, max_size):
        try:
            return '%.0f MB' % (float(max_size) / 1024 / 1024)
        except Exception:
            return str(max_size)

    def _raise_size_limit_error(self, max_size):
        raise UserError(_(
            'The remote file is larger than the allowed limit (%s). '
            'Increase the download limit on the manufacturer record if this file is trusted.'
        ) % self._download_limit_label(max_size))

    def _download_url(self, url, required=True, max_size=None):
        if max_size is None:
            max_size = self._download_limit_bytes(self.max_bc3_download_size_mb, default_mb=500)
        parsed = urllib.parse.urlparse(url or '')
        filename = sanitize_text(posixpath.basename(urllib.parse.unquote(parsed.path)) or 'download.bc3')
        try:
            parsed = self._validate_download_url(url)
            filename = sanitize_text(posixpath.basename(urllib.parse.unquote(parsed.path)) or filename)
            request = urllib.request.Request(url, headers={'User-Agent': 'Odoo-FIEBDC-BC3-Importer/1.0'})
            with urllib.request.urlopen(request, timeout=30, context=self._get_ssl_context()) as response:
                final_url = response.geturl()
                final_parsed = self._validate_download_url(final_url)
                filename = sanitize_text(posixpath.basename(urllib.parse.unquote(final_parsed.path)) or filename)
                content_length = response.headers.get('Content-Length')
                if content_length and int(content_length) > max_size:
                    self._raise_size_limit_error(max_size)
                chunks = []
                total = 0
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > max_size:
                        self._raise_size_limit_error(max_size)
                    chunks.append(chunk)
                payload = b''.join(chunks)
                if not payload and required:
                    raise UserError(_('The downloaded file is empty.'))
                return filename, payload
        except UserError:
            if required:
                raise
            return filename, None
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, ssl.SSLError, ValueError) as exc:
            if required:
                if self._is_ssl_certificate_error(exc) and not self.allow_insecure_ssl:
                    raise UserError(_(
                        'Cannot verify the SSL certificate for URL %s: %s\n\n'
                        'Install/update CA certificates on the Odoo server or open the '
                        'manufacturer record and enable "Permitir SSL sin verificar" '
                        'only if this is a trusted manufacturer URL.'
                    ) % (url, exc))
                raise UserError(_('Cannot download URL %s: %s') % (url, exc))
            return filename, None

    def _is_zip_payload(self, filename, payload):
        if not payload:
            return False
        if sanitize_text(filename).lower().endswith('.zip'):
            return True
        try:
            return zipfile.is_zipfile(io.BytesIO(payload))
        except Exception:
            return False

    def _is_rar_payload(self, filename, payload):
        if not payload:
            return False
        clean_name = sanitize_text(filename).lower()
        if clean_name.endswith('.rar'):
            return True
        return payload.startswith(b'Rar!\x1a\x07\x00') or payload.startswith(b'Rar!\x1a\x07\x01\x00')

    def _archive_handler_for_payload(self, filename, payload):
        if self._is_zip_payload(filename, payload):
            return SafeZipBC3(payload, **self._zip_limits())
        if self._is_rar_payload(filename, payload):
            return SafeRarBC3(payload, **self._zip_limits())
        return None

    def _zip_limits(self):
        bc3_limit = self._download_limit_bytes(self.max_bc3_download_size_mb, default_mb=500)
        related_limit = self._download_limit_bytes(self.max_related_file_size_mb, default_mb=75)
        return {
            'max_total_size': max(bc3_limit, related_limit) * 4,
            'max_file_size': max(bc3_limit, related_limit),
        }

    def _selected_bc3_name_for_archive(self):
        name = sanitize_text(self.bc3_filename or '').strip()
        return name if name.lower().endswith('.bc3') else None

    def _load_bc3_url(self):
        try:
            filename, payload = self._download_url(self.bc3_url, required=True)
            archive_handler = self._archive_handler_for_payload(filename, payload)
            if archive_handler:
                bc3_name, bc3_bytes = archive_handler.read_bc3(self._selected_bc3_name_for_archive())
                data = BC3Parser().parse(bc3_bytes, sanitize_text(bc3_name))
                return data, FiebdcZipUrlResourceHandler(self, data, archive_handler), filename, payload
            bc3_name = sanitize_text(self.bc3_filename or filename or 'download.bc3')
            data = BC3Parser().parse(payload, bc3_name)
            return data, FiebdcUrlResourceHandler(self, data), filename, payload
        except BC3ParseError as exc:
            raise UserError(str(exc))
        except Exception as exc:
            if isinstance(exc, UserError):
                raise
            raise UserError(_('Cannot read the BC3/ZIP/RAR URL: %s') % exc)

    def _parse_bc3_url(self):
        data, resource_handler, _source_filename, _source_payload = self._load_bc3_url()
        return data, resource_handler

    def _save_batch_source_attachment(self, batch, source_filename, payload):
        if not payload:
            return False
        attachment = self.env['ir.attachment'].sudo().create({
            'name': sanitize_text(source_filename or batch.bc3_filename or batch.name),
            'type': 'binary',
            'datas': b64(payload),
            'res_model': 'fiebdc.import.batch',
            'res_id': batch.id,
            'mimetype': guess_mimetype(sanitize_text(source_filename or batch.bc3_filename or 'catalogo.bc3')),
            'description': sanitize_text('Archivo fuente para importacion FIEBDC por lotes.'),
        })
        batch.write({'source_attachment_id': attachment.id})
        return attachment

    def _stage_import_lines(self, batch, importable):
        Line = self.env['fiebdc.import.line'].sudo()
        vals_list = []
        for sequence, concept in enumerate(importable, start=1):
            vals_list.append({
                'batch_id': batch.id,
                'sequence': sequence,
                'code': sanitize_text(concept.code),
                'name': sanitize_text(concept.summary or concept.code),
                'concept_json': json_dumps(self._concept_to_dict(concept)),
                'state': 'pending',
            })
            if len(vals_list) >= 500:
                Line.create(vals_list)
                vals_list = []
        if vals_list:
            Line.create(vals_list)

    def _concept_to_dict(self, concept):
        def ref_to_dict(ref):
            return sanitize_value({
                'code': ref.code,
                'filename': ref.filename,
                'source': ref.source,
                'type_code': ref.type_code,
                'description': ref.description,
                'url_ext': ref.url_ext,
            })
        return sanitize_value({
            'code': concept.code,
            'aliases': concept.aliases,
            'unit': concept.unit,
            'summary': concept.summary,
            'prices': concept.prices,
            'price_dates': concept.price_dates,
            'concept_type': concept.concept_type,
            'text': concept.text,
            'technical': concept.technical,
            'graphics': [ref_to_dict(ref) for ref in concept.graphics],
            'attachments': [ref_to_dict(ref) for ref in concept.attachments],
            'raw_c_record': concept.raw_c_record,
        })

    def _concept_from_json(self, concept_json):
        payload = sanitize_value(json.loads(concept_json or '{}'))
        def make_ref(data):
            return BC3AttachmentRef(
                code=sanitize_text(data.get('code')),
                filename=sanitize_text(data.get('filename')),
                source=sanitize_text(data.get('source')),
                type_code=sanitize_text(data.get('type_code')),
                description=sanitize_text(data.get('description')),
                url_ext=sanitize_text(data.get('url_ext')),
            )
        return BC3Concept(
            code=sanitize_text(payload.get('code')),
            aliases=[sanitize_text(alias) for alias in payload.get('aliases') or []],
            unit=sanitize_text(payload.get('unit')),
            summary=sanitize_text(payload.get('summary')),
            prices=payload.get('prices') or [],
            price_dates=[sanitize_text(date) for date in payload.get('price_dates') or []],
            concept_type=sanitize_text(payload.get('concept_type')),
            text=sanitize_text(payload.get('text')),
            technical=sanitize_value(payload.get('technical') or {}),
            graphics=[make_ref(ref) for ref in payload.get('graphics') or []],
            attachments=[make_ref(ref) for ref in payload.get('attachments') or []],
            raw_c_record=sanitize_text(payload.get('raw_c_record')),
        )

    def _batch_data_stub(self, batch):
        return BC3Data(
            bc3_filename=sanitize_text(batch.bc3_filename),
            encoding=sanitize_text(batch.bc3_encoding or ''),
            url_base=sanitize_text(batch.bc3_url_base or ''),
        )

    def _resource_handler_for_batch(self, batch, data):
        payload = b''
        if batch.source_attachment_id and batch.source_attachment_id.datas:
            payload = base64.b64decode(batch.source_attachment_id.datas)
        filename = sanitize_text(batch.zip_filename or batch.bc3_filename or 'catalogo.bc3')
        archive_handler = self._archive_handler_for_payload(filename, payload) if payload else None
        if archive_handler:
            return FiebdcZipUrlResourceHandler(self, data, archive_handler)
        return FiebdcUrlResourceHandler(self, data)

    def _close_resource_handler(self, resource_handler):
        archive_handler = getattr(resource_handler, 'zip_handler', None)
        if archive_handler and hasattr(archive_handler, 'close'):
            archive_handler.close()

    def _process_import_batch(self, batch, limit=None):
        self.ensure_one()
        batch = batch.sudo()
        limit = max(int(limit or batch.batch_size or 200), 1)
        if batch.state in ('done', 'error'):
            return batch
        data = self._batch_data_stub(batch)
        resource_handler = self._resource_handler_for_batch(batch, data)
        Line = self.env['fiebdc.import.line'].sudo()
        lines = Line.search([('batch_id', '=', batch.id), ('state', '=', 'pending')], order='sequence,id', limit=limit)
        if not lines:
            final_state = 'error' if batch.error_count else 'done'
            batch.write({'state': final_state, 'finished_at': fields.Datetime.now()})
            self._close_resource_handler(resource_handler)
            return batch
        counters = {
            'created_products': batch.created_products,
            'updated_products': batch.updated_products,
            'skipped_products': batch.skipped_products,
            'attachments_created': batch.attachments_created,
            'warning_count': batch.warning_count,
            'error_count': batch.error_count,
            'processed_concepts': batch.processed_concepts,
        }
        batch.write({'state': 'running', 'started_at': batch.started_at or fields.Datetime.now()})
        for line in lines:
            try:
                with self.env.cr.savepoint():
                    concept = self._concept_from_json(line.concept_json)
                    product, created = self._create_or_update_product(concept, data)
                    if not product:
                        counters['skipped_products'] += 1
                        line.write({'state': 'skipped', 'message': sanitize_text('Product exists and update is disabled.')})
                    else:
                        if created:
                            counters['created_products'] += 1
                        else:
                            counters['updated_products'] += 1
                        attachment_count = self._import_concept_attachments(product, concept, resource_handler, batch)
                        counters['attachments_created'] += attachment_count
                        line.write({
                            'state': 'done',
                            'product_id': product.id,
                            'attachment_count': attachment_count,
                            'message': sanitize_text('Imported'),
                        })
            except Exception as exc:
                counters['error_count'] += 1
                line.write({'state': 'error', 'message': sanitize_text(str(exc))})
                self._log(batch, 'error', line.code, str(exc))
            counters['processed_concepts'] += 1
        remaining = Line.search_count([('batch_id', '=', batch.id), ('state', '=', 'pending')])
        vals = dict(counters)
        if remaining:
            vals['state'] = 'partial'
        else:
            vals['state'] = 'error' if counters['error_count'] else 'done'
            vals['finished_at'] = fields.Datetime.now()
        batch.write(vals)
        self.write({'last_import_batch_id': batch.id, 'last_import_date': fields.Datetime.now()})
        self._close_resource_handler(resource_handler)
        self.env.cr.commit()
        return batch

    def _create_or_update_product(self, concept, data):
        Product = self.env['product.template'].sudo()
        code = sanitize_text(concept.code)
        domain = ['|', ('bc3_code', '=', code), ('default_code', '=', code)]
        product = Product.search(domain, limit=1)
        if product and not self.update_existing:
            self._log_product_warning(code, 'Product exists and update is disabled.')
            return False, False
        vals = self._product_values(concept, data)
        if product:
            product.write(vals)
            return product, False
        product = Product.create(vals)
        return product, True

    def _product_values(self, concept, data):
        first_price = concept.prices[0] if concept.prices else 0.0
        first_date = parse_bc3_date(concept.price_dates[0]) if concept.price_dates else False
        uom = self._map_uom(concept.unit)
        vals = {
            'name': sanitize_text(concept.summary or concept.code),
            'default_code': sanitize_text(concept.code),
            'bc3_code': sanitize_text(concept.code),
            'bc3_alias_codes': sanitize_text(','.join(concept.aliases)),
            'bc3_type': sanitize_text(concept.concept_type),
            'bc3_unit_code': sanitize_text(concept.unit),
            'bc3_source_file': sanitize_text(data.bc3_filename),
            'bc3_raw_prices_json': json_dumps(concept.prices),
            'bc3_technical_json': json_dumps(concept.technical),
            'bc3_long_description': html.escape(sanitize_text(concept.text)).replace('\n', '<br/>'),
            'list_price': first_price,
        }
        if first_date:
            vals['bc3_price_date'] = first_date
        if concept.text:
            vals['description_sale'] = sanitize_text(concept.text)
        Product = self.env['product.template']
        if uom:
            if 'uom_id' in Product._fields:
                vals['uom_id'] = uom.id
            if 'uom_po_id' in Product._fields:
                vals['uom_po_id'] = uom.id
        product_type = self._map_product_type(concept.concept_type)
        if 'type' in Product._fields:
            vals['type'] = product_type
        elif 'detailed_type' in Product._fields:
            vals['detailed_type'] = product_type
        if 'is_storable' in Product._fields:
            vals['is_storable'] = bool(product_type == 'consu' and self.track_inventory)
        return sanitize_value(vals)

    def _map_product_type(self, bc3_type):
        if bc3_type == '1':
            return 'service'
        if bc3_type == '2':
            return 'service'
        if bc3_type == '3':
            return self.default_product_type
        return self.default_product_type

    def _map_uom(self, unit_code):
        unit_code = sanitize_text(unit_code).strip().lower().replace('²', '2').replace('³', '3')
        xmlid_map = {
            '': 'uom.product_uom_unit',
            'u': 'uom.product_uom_unit',
            'ud': 'uom.product_uom_unit',
            'uds': 'uom.product_uom_unit',
            'm': 'uom.product_uom_meter',
            'm2': 'uom.product_uom_square_meter',
            'm3': 'uom.product_uom_cubic_meter',
            'kg': 'uom.product_uom_kgm',
            'g': 'uom.product_uom_gram',
            't': 'uom.product_uom_ton',
            'h': 'uom.product_uom_hour',
            'hr': 'uom.product_uom_hour',
            'dia': 'uom.product_uom_day',
            'd': 'uom.product_uom_day',
            'l': 'uom.product_uom_litre',
            'lt': 'uom.product_uom_litre',
        }
        xmlid = xmlid_map.get(unit_code)
        if xmlid:
            uom = self.env.ref(xmlid, raise_if_not_found=False)
            if uom:
                return uom
        Uom = self.env['uom.uom'].sudo()
        if unit_code:
            uom = Uom.search([('name', '=ilike', unit_code)], limit=1)
            if uom:
                return uom
            uom = Uom.search([('name', 'ilike', unit_code)], limit=1)
            if uom:
                return uom
        return self.env.ref('uom.product_uom_unit', raise_if_not_found=False)

    def _import_concept_attachments(self, product, concept, resource_handler, batch):
        created = 0
        for ref in concept.all_attachment_refs():
            if ref.is_image and not self.import_images:
                continue
            if (not ref.is_image) and not self.import_attachments:
                continue
            normalized_name, payload = resource_handler.read_related_file(ref)
            if normalized_name and payload is None:
                self._log(batch, 'warning', concept.code, 'Blocked executable attachment: %s' % ref.filename)
                continue
            if not payload:
                self._log(batch, 'warning', concept.code, 'Remote attachment not found: %s' % ref.filename)
                continue
            attachment_name = sanitize_text('%s - %s' % (concept.code, posixpath.basename(sanitize_text(normalized_name or ref.filename))))
            if self.skip_duplicate_attachments:
                existing = self.env['ir.attachment'].sudo().search([
                    ('res_model', '=', 'product.template'),
                    ('res_id', '=', product.id),
                    ('name', '=', sanitize_text(attachment_name)),
                ], limit=1)
                if existing:
                    continue
            attachment = self.env['ir.attachment'].sudo().create({
                'name': sanitize_text(attachment_name),
                'datas': b64(payload),
                'res_model': 'product.template',
                'res_id': product.id,
                'mimetype': guess_mimetype(sanitize_text(normalized_name or ref.filename)),
                'description': sanitize_text(ref.description or ref.source),
            })
            self._create_product_document_if_available(attachment, batch, concept.code)
            created += 1
            if ref.is_image and self.set_first_image and ('image_1920' in product._fields):
                if self.overwrite_image or not product.image_1920:
                    product.write({'image_1920': b64(payload)})
        return created

    def _create_product_document_if_available(self, attachment, batch, code):
        if not self.env['ir.model'].sudo().search_count([('model', '=', 'product.document')]):
            return False
        try:
            existing = self.env['product.document'].sudo().search([('ir_attachment_id', '=', attachment.id)], limit=1)
            if not existing:
                self.env['product.document'].sudo().create({'ir_attachment_id': attachment.id})
            return True
        except Exception as exc:
            self._log(batch, 'warning', code, 'Attachment created but product.document link failed: %s' % exc)
            return False

    def _log(self, batch, level, code, message):
        self.env['fiebdc.import.log'].sudo().create({
            'batch_id': batch.id,
            'level': level,
            'bc3_code': sanitize_text(code),
            'message': sanitize_text(message),
        })

    def _log_product_warning(self, code, message):
        return True

    def _reload_form(self):
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def _open_batch(self, batch):
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'fiebdc.import.batch',
            'res_id': batch.id,
            'view_mode': 'form',
            'target': 'current',
        }
