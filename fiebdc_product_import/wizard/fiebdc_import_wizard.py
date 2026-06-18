# -*- coding: utf-8 -*-
import base64
import html
import posixpath
import zipfile

from odoo import _, fields, models
from odoo.exceptions import UserError

from ..models.fiebdc_parser import (
    BC3ParseError,
    BC3Parser,
    SafeZipBC3,
    b64,
    guess_mimetype,
    json_dumps,
    parse_bc3_date,
)


class FiebdcImportWizard(models.TransientModel):
    _name = 'fiebdc.import.wizard'
    _description = 'Import FIEBDC BC3 Products'

    zip_file = fields.Binary(string='ZIP File', required=True, attachment=False)
    zip_filename = fields.Char(string='ZIP Filename')
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

    preview_html = fields.Html(string='Preview', readonly=True)

    def action_preview(self):
        self.ensure_one()
        data, _zip_handler = self._parse_zip()
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
            html.escape(data.encoding or ''),
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
        batch = self.env['fiebdc.import.batch'].create({
            'name': self.zip_filename or 'FIEBDC Import',
            'zip_filename': self.zip_filename,
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
                counters['attachments_created'] += self._import_concept_attachments(product, concept, zip_handler, batch)
            except Exception as exc:
                counters['error_count'] += 1
                self._log(batch, 'error', concept.code, str(exc))
        state = 'error' if counters['error_count'] else 'done'
        batch.write({'state': state, **counters})
        return self._open_batch(batch)

    def _parse_zip(self):
        if not self.zip_file:
            raise UserError(_('Please upload a ZIP file.'))
        try:
            zip_bytes = base64.b64decode(self.zip_file)
            zip_handler = SafeZipBC3(zip_bytes)
            bc3_name, bc3_bytes = zip_handler.read_bc3(self.bc3_filename)
            data = BC3Parser().parse(bc3_bytes, bc3_name)
            return data, zip_handler
        except zipfile.BadZipFile as exc:  # noqa: F821
            raise UserError(_('Invalid ZIP file: %s') % exc)
        except BC3ParseError as exc:
            raise UserError(str(exc))
        except Exception as exc:
            raise UserError(_('Cannot read the ZIP/BC3 file: %s') % exc)

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
        if uom:
            vals['uom_id'] = uom.id
            vals['uom_po_id'] = uom.id
        product_type = self._map_product_type(concept.concept_type)
        Product = self.env['product.template']
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
            'bc3_code': code or '',
            'message': message,
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
