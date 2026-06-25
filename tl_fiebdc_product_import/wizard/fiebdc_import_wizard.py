# -*- coding: utf-8 -*-
import base64
import html
import io
import ipaddress
import posixpath
import socket
import ssl
import urllib.error
import urllib.parse
import urllib.request
import zipfile

from odoo import _, fields, models
from odoo.exceptions import UserError

try:
    import certifi
except ImportError:  # pragma: no cover - optional runtime dependency
    certifi = None

from ..models.fiebdc_parser import (
    BC3ParseError,
    BC3Parser,
    SafeZipBC3,
    SafeRarBC3,
    b64,
    guess_mimetype,
    json_dumps,
    parse_bc3_date,
    sanitize_text,
    sanitize_value,
)



class EmptyResourceHandler:
    def read_related_file(self, filename):
        return None, None


class FiebdcImportWizard(models.TransientModel):
    _name = 'fiebdc.import.wizard'
    _description = 'Import FIEBDC BC3 Products'

    source_type = fields.Selection([
        ('upload', 'Subir archivo'),
        ('url', 'Descargar archivo desde URL'),
    ], string='Origen', default='upload', required=True)
    zip_attachment_ids = fields.Many2many(
        'ir.attachment',
        'fiebdc_import_wizard_ir_attachment_rel',
        'wizard_id',
        'attachment_id',
        string='Archivo BC3/ZIP/RAR',
        help='Upload one BC3, ZIP or RAR file containing the BC3 and related images/PDFs.',
    )
    # Main upload field. The filename is stored separately in zip_filename.
    # It must be Binary for the Odoo web client to render an upload control with widget="binary".
    zip_file = fields.Binary(string='Archivo BC3/ZIP/RAR', attachment=False)
    zip_filename = fields.Char(string='Nombre archivo')
    zip_url = fields.Char(
        string='URL del archivo',
        help='URL HTTP/HTTPS desde la que descargar un BC3, ZIP o RAR con el BC3 y sus adjuntos. Evita el limite de subida del navegador/proxy.',
    )
    allow_insecure_ssl = fields.Boolean(
        string='Permitir SSL sin verificar',
        help='Usar solo para URLs de confianza con una cadena SSL no verificable.',
    )
    max_zip_download_size_mb = fields.Integer(
        string='Limite descarga archivo (MB)',
        default=500,
        required=True,
        help='Tamano maximo permitido para descargar el archivo desde URL.',
    )
    bc3_filename = fields.Char(string='BC3 Filename', help='Optional. Leave empty to use the first .bc3 file found in the ZIP.')

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
        help='Numero de productos que se procesan antes de guardar avance en la base de datos.',
    )

    preview_html = fields.Html(string='Preview', readonly=True)

    def action_preview(self):
        self.ensure_one()
        data, _zip_handler = self._parse_zip()
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
            <b>Origen:</b> %s<br/>
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
            html.escape(sanitize_text(self.zip_url if self.source_type == 'url' else self.zip_filename)),
            html.escape(sanitize_text(data.encoding)),
            len(data.concepts),
            len(importable),
            ''.join(rows) or '<tr><td colspan="5">No importable concepts found.</td></tr>',
            '<ul>%s</ul>' % warning_rows if warning_rows else '',
        )
        return self._reload_wizard()

    def action_import(self):
        self.ensure_one()
        data, zip_handler = self._parse_zip()
        importable = data.importable_concepts(self.import_type_4, self.import_type_5)
        batch = self.env['fiebdc.import.batch'].sudo().create({
            'name': sanitize_text(self.zip_filename or self.zip_url) or 'FIEBDC Import',
            'zip_filename': sanitize_text(self.zip_filename),
            'bc3_url': sanitize_text(self.zip_url) if self.source_type == 'url' else False,
            'bc3_filename': sanitize_text(data.bc3_filename),
            'total_concepts': len(data.concepts),
            'importable_concepts': len(importable),
            'batch_size': max(int(self.import_batch_size or 200), 1),
            'state': 'running' if importable and not self.dry_run else 'draft',
        })
        counters = {
            'created_products': 0,
            'updated_products': 0,
            'skipped_products': 0,
            'attachments_created': 0,
            'warning_count': len(data.warnings),
            'error_count': 0,
        }
        for warning in data.warnings:
            self._log(batch, 'warning', '', warning)
        if self.dry_run:
            batch.write({'state': 'done', **counters})
            return self._open_batch(batch)

        batch_size = max(int(self.import_batch_size or 200), 1)
        processed = 0
        for concept in importable:
            try:
                with self.env.cr.savepoint():
                    product, created = self._create_or_update_product(concept, data)
                    if not product:
                        counters['skipped_products'] += 1
                    else:
                        if created:
                            counters['created_products'] += 1
                        else:
                            counters['updated_products'] += 1
                        counters['attachments_created'] += self._import_concept_attachments(product, concept, zip_handler, batch)
            except Exception as exc:
                counters['error_count'] += 1
                self._log(batch, 'error', concept.code, str(exc))
            processed += 1
            if processed % batch_size == 0:
                batch.write({'state': 'partial', 'processed_concepts': processed, **counters})
                self.env.cr.commit()
        state = 'error' if counters['error_count'] else 'done'
        batch.write({'state': state, 'processed_concepts': processed, 'finished_at': fields.Datetime.now(), **counters})
        return self._open_batch(batch)

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

    def _download_limit_bytes(self, size_mb, default_mb=500):
        try:
            size_mb = int(size_mb or 0)
        except (TypeError, ValueError):
            size_mb = 0
        if size_mb <= 0:
            size_mb = default_mb
        return size_mb * 1024 * 1024

    def _raise_size_limit_error(self, max_size):
        raise UserError(_(
            'The remote file is larger than the allowed limit (%s MB). '
            'Increase the URL download limit if this file is trusted.'
        ) % int(max_size / 1024 / 1024))

    def _download_zip_url(self):
        self.ensure_one()
        if not self.zip_url:
            raise UserError(_('Please enter a file URL.'))
        max_size = self._download_limit_bytes(self.max_zip_download_size_mb, default_mb=500)
        parsed = self._validate_download_url(self.zip_url)
        filename = sanitize_text(posixpath.basename(urllib.parse.unquote(parsed.path)) or 'import.bc3')
        try:
            request = urllib.request.Request(self.zip_url, headers={'User-Agent': 'Odoo-FIEBDC-BC3-Importer/1.0'})
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
                if not payload:
                    raise UserError(_('The downloaded file is empty.'))
                self.zip_filename = filename
                return payload, filename
        except UserError:
            raise
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, ssl.SSLError, ValueError) as exc:
            raise UserError(_('Cannot download file URL %s: %s') % (self.zip_url, exc))

    def _get_uploaded_archive(self):
        self.ensure_one()
        if self.source_type == 'url':
            return self._download_zip_url()

        attachments = self.zip_attachment_ids
        if attachments:
            if len(attachments) != 1:
                raise UserError(_('Please upload exactly one BC3, ZIP or RAR file.'))
            attachment = attachments[0].sudo()
            filename = attachment.name or self.zip_filename or 'import.bc3'
            if not attachment.datas:
                raise UserError(_('The uploaded file is empty.'))
            return base64.b64decode(attachment.datas), filename

        if self.zip_file:
            filename = self.zip_filename or 'import.bc3'
            return base64.b64decode(self.zip_file), filename

        raise UserError(_('Please upload a BC3, ZIP or RAR file or choose URL as source.'))

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

    def _archive_limits(self):
        max_size = self._download_limit_bytes(self.max_zip_download_size_mb, default_mb=500)
        return {
            'max_total_size': max(max_size * 4, 250 * 1024 * 1024),
            'max_file_size': max_size,
        }

    def _archive_handler_for_payload(self, filename, payload):
        if self._is_zip_payload(filename, payload):
            return SafeZipBC3(payload, **self._archive_limits())
        if self._is_rar_payload(filename, payload):
            return SafeRarBC3(payload, **self._archive_limits())
        return None

    def _parse_zip(self):
        try:
            payload, filename = self._get_uploaded_archive()
            if filename and not self.zip_filename:
                self.zip_filename = filename
            archive_handler = self._archive_handler_for_payload(filename, payload)
            if archive_handler:
                bc3_name, bc3_bytes = archive_handler.read_bc3(self.bc3_filename)
                data = BC3Parser().parse(bc3_bytes, bc3_name)
                return data, archive_handler
            bc3_name = sanitize_text(self.bc3_filename or filename or 'import.bc3')
            data = BC3Parser().parse(payload, bc3_name)
            return data, EmptyResourceHandler()
        except zipfile.BadZipFile as exc:  # noqa: F821
            raise UserError(_('Invalid ZIP file: %s') % exc)
        except BC3ParseError as exc:
            raise UserError(str(exc))
        except Exception as exc:
            raise UserError(_('Cannot read the BC3/ZIP/RAR file: %s') % exc)

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
            # Odoo 19 no longer exposes uom_po_id on product.template in some builds.
            # Keep compatibility with older databases by writing it only when it exists.
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

    def _import_concept_attachments(self, product, concept, zip_handler, batch):
        created = 0
        for ref in concept.all_attachment_refs():
            if ref.is_image and not self.import_images:
                continue
            if (not ref.is_image) and not self.import_attachments:
                continue
            normalized_name, payload = zip_handler.read_related_file(ref.filename)
            if normalized_name and payload is None:
                self._log(batch, 'warning', concept.code, 'Blocked executable attachment: %s' % ref.filename)
                continue
            if not payload:
                self._log(batch, 'warning', concept.code, 'Attachment not found in ZIP: %s' % ref.filename)
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
        # In Odoo 19, product documents are product.document records delegating to ir.attachment.
        # Creating this wrapper makes imported PDFs/images visible from the product Documents smart button.
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
        # Used before a batch log exists in some edge cases.
        return True

    def _reload_wizard(self):
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def _open_batch(self, batch):
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'fiebdc.import.batch',
            'res_id': batch.id,
            'view_mode': 'form',
            'target': 'current',
        }
