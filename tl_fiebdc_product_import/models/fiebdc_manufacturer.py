# -*- coding: utf-8 -*-
import base64
import html
import ipaddress
import posixpath
import socket
import urllib.error
import urllib.parse
import urllib.request

from odoo import _, fields, models
from odoo.exceptions import UserError

from .fiebdc_parser import (
    BC3ParseError,
    BC3Parser,
    EXECUTABLE_EXTENSIONS,
    b64,
    guess_mimetype,
    json_dumps,
    parse_bc3_date,
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
        filename = (ref.filename or '').strip().replace('\\', '/')
        if not filename:
            return []
        parsed_filename = urllib.parse.urlparse(filename)
        if parsed_filename.scheme in ('http', 'https'):
            return [filename]

        candidates = []
        source_dir = self._as_directory_url(self.manufacturer.bc3_url)
        data_base = self._as_directory_url(self.data.url_base)
        ref_ext = (ref.url_ext or '').strip().replace('\\', '/')
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

        # Keep order while removing duplicates.
        seen = set()
        result = []
        for url in candidates:
            if url and url not in seen:
                result.append(url)
                seen.add(url)
        return result

    def read_related_file(self, ref):
        for url in self._candidate_urls(ref):
            parsed = urllib.parse.urlparse(url)
            normalized_name = posixpath.basename(urllib.parse.unquote(parsed.path)) or posixpath.basename(ref.filename)
            ext = posixpath.splitext(normalized_name.lower())[1]
            if ext in EXECUTABLE_EXTENSIONS:
                return normalized_name, None
            payload = self.manufacturer._download_url(url, required=False, max_size=75 * 1024 * 1024)[1]
            if payload:
                return normalized_name, payload
        return None, None


class FiebdcManufacturer(models.Model):
    _name = 'fiebdc.manufacturer'
    _description = 'FIEBDC Manufacturer'
    _inherit = ['mail.thread']
    _order = 'name'

    name = fields.Char(string='Fabricante', required=True, tracking=True)
    active = fields.Boolean(default=True)
    bc3_url = fields.Char(
        string='URL del fichero BC3',
        required=True,
        tracking=True,
        help='URL HTTP/HTTPS desde la que se descargara el fichero BC3 del fabricante.',
    )
    bc3_filename = fields.Char(
        string='Nombre del BC3',
        help='Opcional. Si se deja vacio se usara el nombre del fichero descargado.',
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
                html.escape(concept.code or ''),
                html.escape(concept.unit or ''),
                html.escape(concept.summary or ''),
                html.escape(str(concept.prices[0]) if concept.prices else ''),
                html.escape(str(len(concept.all_attachment_refs()))),
            ))
        warning_rows = ''.join('<li>%s</li>' % html.escape(w) for w in data.warnings[:20])
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
            html.escape(data.bc3_filename or ''),
            html.escape(self.bc3_url or ''),
            html.escape(data.encoding or ''),
            len(data.concepts),
            len(importable),
            ''.join(rows) or '<tr><td colspan="5">No importable concepts found.</td></tr>',
            '<ul>%s</ul>' % warning_rows if warning_rows else '',
        )
        return self._reload_form()

    def action_import(self):
        self.ensure_one()
        data, resource_handler = self._parse_bc3_url()
        importable = data.importable_concepts(self.import_type_4, self.import_type_5)
        batch = self.env['fiebdc.import.batch'].sudo().create({
            'name': '%s - %s' % (self.name, data.bc3_filename or 'FIEBDC Import'),
            'manufacturer_id': self.id,
            'bc3_url': self.bc3_url,
            'zip_filename': False,
            'bc3_filename': data.bc3_filename,
            'total_concepts': len(data.concepts),
            'importable_concepts': len(importable),
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
            self.write({'last_import_batch_id': batch.id, 'last_import_date': fields.Datetime.now()})
            return self._open_batch(batch)

        for concept in importable:
            try:
                product, created = self._create_or_update_product(concept, data)
                if not product:
                    counters['skipped_products'] += 1
                    continue
                if created:
                    counters['created_products'] += 1
                else:
                    counters['updated_products'] += 1
                counters['attachments_created'] += self._import_concept_attachments(product, concept, resource_handler, batch)
            except Exception as exc:
                counters['error_count'] += 1
                self._log(batch, 'error', concept.code, str(exc))
        state = 'error' if counters['error_count'] else 'done'
        batch.write({'state': state, **counters})
        self.write({'last_import_batch_id': batch.id, 'last_import_date': fields.Datetime.now()})
        return self._open_batch(batch)

    def action_open_last_import_batch(self):
        self.ensure_one()
        if not self.last_import_batch_id:
            raise UserError(_('This manufacturer has no imports yet.'))
        return self._open_batch(self.last_import_batch_id)

    def _validate_download_url(self, url):
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

    def _download_url(self, url, required=True, max_size=75 * 1024 * 1024):
        parsed = urllib.parse.urlparse(url or '')
        filename = posixpath.basename(urllib.parse.unquote(parsed.path)) or 'download.bc3'
        try:
            parsed = self._validate_download_url(url)
            filename = posixpath.basename(urllib.parse.unquote(parsed.path)) or filename
            request = urllib.request.Request(url, headers={'User-Agent': 'Odoo-FIEBDC-BC3-Importer/1.0'})
            with urllib.request.urlopen(request, timeout=30) as response:
                final_url = response.geturl()
                final_parsed = self._validate_download_url(final_url)
                filename = posixpath.basename(urllib.parse.unquote(final_parsed.path)) or filename
                content_length = response.headers.get('Content-Length')
                if content_length and int(content_length) > max_size:
                    raise UserError(_('The remote file is larger than the allowed limit.'))
                chunks = []
                total = 0
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > max_size:
                        raise UserError(_('The remote file is larger than the allowed limit.'))
                    chunks.append(chunk)
                payload = b''.join(chunks)
                if not payload and required:
                    raise UserError(_('The downloaded file is empty.'))
                return filename, payload
        except UserError:
            if required:
                raise
            return filename, None
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
            if required:
                raise UserError(_('Cannot download URL %s: %s') % (url, exc))
            return filename, None

    def _parse_bc3_url(self):
        try:
            filename, bc3_bytes = self._download_url(self.bc3_url, required=True)
            bc3_name = self.bc3_filename or filename or 'download.bc3'
            data = BC3Parser().parse(bc3_bytes, bc3_name)
            return data, FiebdcUrlResourceHandler(self, data)
        except BC3ParseError as exc:
            raise UserError(str(exc))
        except Exception as exc:
            if isinstance(exc, UserError):
                raise
            raise UserError(_('Cannot read the BC3 URL: %s') % exc)

    def _create_or_update_product(self, concept, data):
        Product = self.env['product.template'].sudo()
        domain = ['|', ('bc3_code', '=', concept.code), ('default_code', '=', concept.code)]
        product = Product.search(domain, limit=1)
        if product and not self.update_existing:
            self._log_product_warning(concept.code, 'Product exists and update is disabled.')
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
            'name': concept.summary or concept.code,
            'default_code': concept.code,
            'bc3_code': concept.code,
            'bc3_alias_codes': ','.join(concept.aliases),
            'bc3_type': concept.concept_type,
            'bc3_unit_code': concept.unit,
            'bc3_source_file': data.bc3_filename,
            'bc3_raw_prices_json': json_dumps(concept.prices),
            'bc3_technical_json': json_dumps(concept.technical),
            'bc3_long_description': html.escape(concept.text or '').replace('\n', '<br/>'),
            'list_price': first_price,
        }
        if first_date:
            vals['bc3_price_date'] = first_date
        if concept.text:
            vals['description_sale'] = concept.text
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
        return vals

    def _map_product_type(self, bc3_type):
        if bc3_type == '1':
            return 'service'
        if bc3_type == '2':
            return 'service'
        if bc3_type == '3':
            return self.default_product_type
        return self.default_product_type

    def _map_uom(self, unit_code):
        unit_code = (unit_code or '').strip().lower().replace('²', '2').replace('³', '3')
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
            attachment_name = '%s - %s' % (concept.code, posixpath.basename(normalized_name or ref.filename))
            if self.skip_duplicate_attachments:
                existing = self.env['ir.attachment'].sudo().search([
                    ('res_model', '=', 'product.template'),
                    ('res_id', '=', product.id),
                    ('name', '=', attachment_name),
                ], limit=1)
                if existing:
                    continue
            attachment = self.env['ir.attachment'].sudo().create({
                'name': attachment_name,
                'datas': b64(payload),
                'res_model': 'product.template',
                'res_id': product.id,
                'mimetype': guess_mimetype(normalized_name or ref.filename),
                'description': ref.description or ref.source,
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
            'bc3_code': code or '',
            'message': message,
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
