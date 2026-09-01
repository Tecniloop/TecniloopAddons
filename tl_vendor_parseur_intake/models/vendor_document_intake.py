# -*- coding: utf-8 -*-
import json
import logging
from datetime import datetime

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools import float_compare, float_is_zero

from .text_utils import normalize_text, texts_match, unique_fuzzy_match

_logger = logging.getLogger(__name__)


def _trace(record, event, **details):
    """Write a DEBUG trace when Odoo detailed logging is enabled."""
    if not _logger.isEnabledFor(logging.DEBUG):
        return
    rec_id = record.id if record else False
    rec_name = False
    if record and getattr(record, "_fields", None) and "name" in record._fields:
        rec_name = record.name
    payload = " ".join("%s=%r" % (key, details[key]) for key in sorted(details))
    _logger.debug(
        "tl_vendor_parseur_intake %s id=%s name=%s %s",
        event,
        rec_id,
        rec_name,
        payload,
    )


DOC_TYPE_ALIASES = {
    'delivery_note': 'delivery_note',
    'albaran': 'delivery_note',
    'albarán': 'delivery_note',
    'dn': 'delivery_note',
    'packing_slip': 'delivery_note',
    'goods_receipt': 'delivery_note',
    'vendor_bill': 'vendor_bill',
    'invoice': 'vendor_bill',
    'factura': 'vendor_bill',
    'bill': 'vendor_bill',
    'in_invoice': 'vendor_bill',
    'return': 'return',
    'devolucion': 'return',
    'devolución': 'return',
    'vendor_return': 'return',
    'abono_albaran': 'return',
    'credit_note': 'vendor_refund',
    'abono': 'vendor_refund',
    'refund': 'vendor_refund',
    'in_refund': 'vendor_refund',
}

HEADER_ALIASES = {
    'supplier_name': ('supplier_name', 'SupplierName', 'vendor_name', 'VendorName', 'supplier'),
    'supplier_vat': ('supplier_vat', 'SupplierVAT', 'vat', 'VAT', 'tax_id', 'TaxID'),
    'company_vat': (
        'company_vat', 'CompanyVAT', 'customer_vat', 'CustomerVAT',
        'buyer_vat', 'BuyerVAT', 'our_vat', 'dest_vat', 'DestVAT',
        'nif_destinatario', 'NIFDestinatario', 'cif_empresa',
    ),
    'company_name': ('company_name', 'CompanyName', 'customer_name', 'buyer_name', 'destinatario'),
    'supplier_code': ('supplier_code', 'SupplierCode', 'vendor_code'),
    'po_number': ('po_number', 'PONumber', 'purchase_order', 'PurchaseOrder', 'pedido', 'order_number'),
    'document_number': ('document_number', 'DocumentNumber', 'DeliveryNumber', 'InvoiceNumber', 'invoice_number', 'albaran', 'number'),
    'document_date': ('document_date', 'DocumentDate', 'DeliveryDate', 'InvoiceDate', 'invoice_date', 'date'),
    'delivery_note_number': ('delivery_note_number', 'DeliveryNoteNumber', 'albaran_number', 'DeliveryNumber'),
    'invoice_number': ('invoice_number', 'InvoiceNumber'),
    'currency': ('currency', 'Currency'),
    'subtotal': ('subtotal', 'SubtotalAmount', 'untaxed'),
    'tax': ('tax', 'TaxAmount', 'total_tax'),
    'total': ('total', 'TotalAmount', 'grand_total'),
}

LINE_ALIASES = {
    'sku': ('sku', 'SKU', 'default_code', 'internal_ref'),
    'supplier_code': ('supplier_code', 'SupplierCode', 'vendor_sku', 'product_code'),
    'barcode': ('barcode', 'Barcode', 'ean'),
    'description': ('description', 'Description', 'name', 'product', 'item'),
    'qty': ('qty', 'quantity', 'Quantity', 'qty_received'),
    'uom': ('uom', 'UoM', 'unit'),
    'unit_price': ('unit_price', 'UnitPrice', 'price', 'price_unit'),
    'line_total': ('line_total', 'LineTotal', 'total', 'amount'),
    'lot': ('lot', 'Lot', 'batch', 'serial'),
    'expiry': ('expiry', 'ExpirationDate', 'best_before', 'BestBefore', 'caducidad', 'use_by'),
}


def _first(payload, keys, default=False):
    if not isinstance(payload, dict):
        return default
    for key in keys:
        if key in payload and payload[key] not in (None, ''):
            return payload[key]
    lowered = {str(k).lower(): v for k, v in payload.items()}
    for key in keys:
        val = lowered.get(str(key).lower())
        if val not in (None, ''):
            return val
    return default


def _to_float(value, default=0.0):
    if value in (None, False, ''):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(' ', '').replace('€', '').replace('$', '')
    if text.count(',') == 1 and text.count('.') == 0:
        text = text.replace(',', '.')
    elif text.count(',') == 1 and text.count('.') >= 1:
        text = text.replace('.', '').replace(',', '.')
    try:
        return float(text)
    except ValueError:
        return default


def _to_date(value):
    if not value:
        return False
    if isinstance(value, datetime):
        return value.date()
    text = str(value).strip()[:10]
    for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y', '%Y/%m/%d'):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return False


class VendorDocumentIntake(models.Model):
    _name = 'vendor.document.intake'
    _description = 'Vendor document intake (Parseur)'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'barcodes.barcode_events_mixin']
    _order = 'id desc'
    def init(self):
        self.env.cr.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS tl_parseur_document_company_uniq
            ON vendor_document_intake (company_id, parseur_document_id)
            WHERE parseur_document_id IS NOT NULL AND parseur_document_id <> '';
            """
        )

    name = fields.Char(default='/', copy=False, readonly=True)
    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company, index=True,
    )
    state = fields.Selection(
        [
            ('draft', 'Draft'),
            ('identified', 'Identified'),
            ('matched', 'Matched'),
            ('applied', 'Applied'),
            ('exception', 'Exception'),
            ('cancelled', 'Cancelled'),
        ],
        default='draft',
        tracking=True,
        required=True,
        index=True,
    )
    document_type = fields.Selection(
        [
            ('delivery_note', 'Delivery Note'),
            ('vendor_bill', 'Vendor Bill'),
            ('return', 'Vendor return'),
            ('vendor_refund', 'Vendor refund'),
        ],
        required=True,
        tracking=True,
        index=True,
    )
    parseur_document_id = fields.Char(index=True, copy=False)
    payload_json = fields.Text()
    raw_attachment_name = fields.Char()

    partner_id = fields.Many2one('res.partner', tracking=True)
    supplier_name = fields.Char()
    supplier_vat = fields.Char()
    supplier_code = fields.Char()
    company_vat = fields.Char()
    company_name_scan = fields.Char(string="Company name on document")

    po_number = fields.Char()
    document_number = fields.Char(index=True)
    document_date = fields.Date()
    delivery_note_number = fields.Char()
    invoice_number = fields.Char()
    currency_id = fields.Many2one('res.currency', default=lambda self: self.env.company.currency_id)
    amount_untaxed = fields.Monetary(currency_field='currency_id')
    amount_tax = fields.Monetary(currency_field='currency_id')
    amount_total = fields.Monetary(currency_field='currency_id')

    purchase_id = fields.Many2one('purchase.order', tracking=True, check_company=True)
    candidate_purchase_ids = fields.Many2many(
        'purchase.order',
        'vendor_intake_po_rel',
        'intake_id',
        'purchase_id',
        string='PO candidates',
    )
    picking_id = fields.Many2one('stock.picking', tracking=True, check_company=True)
    return_picking_id = fields.Many2one('stock.picking', tracking=True, check_company=True)
    invoice_id = fields.Many2one('account.move', tracking=True, check_company=True)
    created_purchase = fields.Boolean(copy=False)

    line_ids = fields.One2many('vendor.document.intake.line', 'intake_id', copy=True)
    exception_reason = fields.Text(tracking=True)
    last_scanned_barcode = fields.Char(copy=False)
    scan_message = fields.Char(copy=False)
    match_score = fields.Float()
    auto_applied = fields.Boolean(copy=False)
    price_exception_count = fields.Integer(compute='_compute_price_exception_count')
    has_pending_price_exception = fields.Boolean(compute='_compute_price_exception_count')
    receipt_exception_count = fields.Integer(compute='_compute_receipt_exception_count')
    price_difference_amount = fields.Monetary(
        compute="_compute_price_difference_amount",
        currency_field="currency_id",
        string="Price difference",
    )
    price_decision = fields.Selection(
        [
            ('pending', 'Pending review'),
            ('accept_document', 'Accept document prices'),
            ('keep_po', 'Keep PO prices'),
        ],
        default='pending',
        tracking=True,
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', '/') == '/':
                company_id = vals.get('company_id') or self.env.company.id
                vals['name'] = (
                    self.env['ir.sequence'].with_company(company_id).next_by_code('vendor.document.intake')
                    or '/'
                )
        return super().create(vals_list)

    @api.depends("line_ids.match_status")
    def _compute_receipt_exception_count(self):
        for intake in self:
            intake.receipt_exception_count = len(
                intake.line_ids.filtered(lambda l: l.match_status in ("over", "unordered", "unidentified"))
            )

    @api.depends(
        "line_ids.price_exception",
        "line_ids.price_variance",
        "line_ids.qty_document",
        "line_ids.price_decision",
    )
    def _compute_price_difference_amount(self):
        for intake in self:
            intake.price_difference_amount = sum(
                line.price_variance * (line.qty_document or 0.0)
                for line in intake.line_ids
                if line.price_exception
            )

    @api.depends('line_ids.price_exception', 'line_ids.price_decision')
    def _compute_price_exception_count(self):
        for intake in self:
            exceptions = intake.line_ids.filtered('price_exception')
            intake.price_exception_count = len(exceptions)
            intake.has_pending_price_exception = bool(
                exceptions.filtered(lambda l: l.price_decision == 'pending')
            )

    # ------------------------------------------------------------------
    # Payload ingest
    # ------------------------------------------------------------------
    @api.model
    def ingest_parseur_payload(self, payload, document_type=None):
        payload = payload or {}
        if isinstance(payload, str):
            payload = json.loads(payload)

        raw_type = document_type or _first(payload, ('document_type', 'DocumentType', 'type'), '')
        doc_type = DOC_TYPE_ALIASES.get(str(raw_type).strip().lower())
        if not doc_type:
            if _first(payload, HEADER_ALIASES['invoice_number']):
                doc_type = 'vendor_bill'
            else:
                doc_type = 'delivery_note'

        header = {field: _first(payload, aliases) for field, aliases in HEADER_ALIASES.items()}
        parseur_id = str(_first(payload, ('DocumentID', 'document_id', 'id'), '') or '')
        try:
            company = self._company_from_vat(
                header.get("company_vat"),
                header.get("company_name"),
                document_type=doc_type,
            )
        except UserError:
            company = self.env.company
        currency = self._resolve_currency(header.get('currency'), company=company)
        lock_key = "tl_parseur:%s:%s:%s" % (
            company.id,
            parseur_id or "",
            header.get("document_number") or header.get("invoice_number") or "",
        )
        self.env.cr.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", [lock_key])

        if parseur_id:
            existing = self.search([
                ('parseur_document_id', '=', parseur_id),
                ('company_id', '=', company.id),
            ], limit=1)
            if existing:
                return existing

        doc_number = header.get('document_number') or header.get('invoice_number') or header.get('delivery_note_number')
        if doc_number:
            duplicate = self.search([
                ('document_type', '=', doc_type),
                ('document_number', '=', doc_number),
                ('company_id', '=', company.id),
                ('state', '!=', 'cancelled'),
            ], limit=1)
            if duplicate and (not header.get('supplier_vat') or duplicate.supplier_vat == header.get('supplier_vat')):
                duplicate.message_post(body=_('Duplicate Parseur payload ignored.'))
                return duplicate

        intake = self.create({
            'document_type': doc_type,
            'company_id': company.id,
            'parseur_document_id': parseur_id or False,
            'payload_json': json.dumps(payload, default=str, ensure_ascii=False),
            'supplier_name': header.get('supplier_name') or False,
            'supplier_vat': header.get('supplier_vat') or False,
            'company_vat': header.get('company_vat') or False,
            'company_name_scan': header.get('company_name') or False,
            'supplier_code': header.get('supplier_code') or False,
            'po_number': header.get('po_number') or False,
            'document_number': doc_number or False,
            'document_date': _to_date(header.get('document_date')),
            'delivery_note_number': header.get('delivery_note_number') or False,
            'invoice_number': header.get('invoice_number') or False,
            'currency_id': currency.id,
            'amount_untaxed': _to_float(header.get('subtotal')),
            'amount_tax': _to_float(header.get('tax')),
            'amount_total': _to_float(header.get('total')),
        })
        _trace(
            intake,
            "ingest",
            parseur_id=parseur_id,
            doc_type=doc_type,
            partner=header.get("supplier_name"),
            vat=header.get("supplier_vat"),
            po=header.get("po_number"),
            lines=len(intake.line_ids),
        )
        intake._create_lines_from_payload(payload)
        intake._normalize_return_quantities()
        _trace(intake, "lines_created", count=len(intake.line_ids), doc_type=intake.document_type)
        intake.with_company(company).action_identify()
        _trace(
            intake,
            "identified",
            state=intake.state,
            partner=intake.partner_id.id,
            purchase=intake.purchase_id.id,
            exception=intake.exception_reason,
        )
        ICP = self.env['ir.config_parameter'].sudo()
        auto = ICP.get_param('vendor_parseur_intake.auto_apply', 'False') == 'True'
        if auto and intake.state in ('identified', 'matched') and not intake.has_pending_price_exception:
            try:
                intake.action_apply()
                intake.auto_applied = True
            except UserError as err:
                intake._set_exception(str(err))
        return intake

    def _create_lines_from_payload(self, payload):
        self.ensure_one()
        items = (
            payload.get('items')
            or payload.get('Items')
            or payload.get('lines')
            or payload.get('Lines')
            or []
        )
        if isinstance(items, dict):
            items = [items]
        vals_list = []
        sequence = 10
        for item in items:
            if not isinstance(item, dict):
                continue
            mapped = {field: _first(item, aliases) for field, aliases in LINE_ALIASES.items()}
            from .qr_utils import parse_expiry_value
            vals_list.append({
                'intake_id': self.id,
                'sequence': sequence,
                'sku': mapped.get('sku') or False,
                'supplier_code': mapped.get('supplier_code') or False,
                'barcode': mapped.get('barcode') or False,
                'description': mapped.get('description') or False,
                'qty_document': _to_float(mapped.get('qty')),
                'uom_name': mapped.get('uom') or False,
                'price_unit': _to_float(mapped.get('unit_price')),
                'price_subtotal': _to_float(mapped.get('line_total')),
                'lot_name': mapped.get('lot') or False,
                'expiry_date': parse_expiry_value(mapped.get('expiry')),
            })
            sequence += 10
        if vals_list:
            self.env['vendor.document.intake.line'].create(vals_list)

    def _resolve_currency(self, code, company=None):
        company = company or (
            self.company_id
            if self and getattr(self, "company_id", False)
            else self.env.company
        )
        if not code:
            return company.currency_id
        currency = self.env['res.currency'].search([('name', '=', str(code).strip().upper())], limit=1)
        return currency or company.currency_id

    # ------------------------------------------------------------------
    # Identify partner + products
    # ------------------------------------------------------------------
    def action_identify(self):
        for intake in self:
            try:
                intake._run_spellcheck()
                intake._identify_company()
                intake._assert_document_vats()
                intake = intake.with_company(intake.company_id)
                intake._identify_partner()
                intake._maybe_vies_check()
                intake.line_ids._identify_product()
                unidentified = intake.line_ids.filtered(lambda l: not l.product_id)
                if not intake.partner_id:
                    intake._set_exception(_('Vendor could not be identified.'))
                    continue
                if unidentified:
                    intake._set_exception(_(
                        'Unidentified products: %s',
                        ', '.join(unidentified.mapped(lambda l: l.description or l.sku or l.supplier_code or '?')),
                    ))
                    continue
                intake._match_purchase_orders()
                _trace(
                    intake,
                    "po_match",
                    purchase=intake.purchase_id.id,
                    candidates=intake.candidate_purchase_ids.ids,
                    score=intake.match_score,
                )
                if not intake.purchase_id:
                    intake.line_ids._compute_price_exceptions()
                intake._apply_price_exception_state()
                _trace(
                    intake,
                    "price_review",
                    exceptions=intake.price_exception_count,
                    pending=intake.has_pending_price_exception,
                    state=intake.state,
                )
            except UserError as err:
                intake._set_exception(str(err))
        return True

    def _normalize_vat(self, vat):
        from .vat_utils import compact_vat
        return compact_vat(vat)

    def _vat_validation_enabled(self):
        return (
            self.env["ir.config_parameter"].sudo().get_param(
                "vendor_parseur_intake.validate_vat_format", "True"
            )
            == "True"
        )

    def _assert_document_vats(self):
        self.ensure_one()
        if not self._vat_validation_enabled():
            return
        from .vat_utils import vat_looks_valid
        errors = []
        if self.company_vat and not vat_looks_valid(self.company_vat):
            errors.append(_("Company VAT format is invalid: %s", self.company_vat))
        if self.supplier_vat and not vat_looks_valid(self.supplier_vat):
            errors.append(_("Supplier VAT format is invalid: %s", self.supplier_vat))
        company_n = self._normalize_vat(self.company_vat)
        supplier_n = self._normalize_vat(self.supplier_vat)
        if company_n and supplier_n and company_n == supplier_n:
            errors.append(_(
                "Supplier VAT and company VAT are the same (%s). "
                "Map nif_destinatario and supplier_vat as two fields in Parseur.",
                self.supplier_vat,
            ))
        if errors:
            raise UserError("\n".join(errors))
        self._maybe_vies_check()

    def _maybe_vies_check(self):
        self.ensure_one()
        if (
            self.env["ir.config_parameter"].sudo().get_param(
                "vendor_parseur_intake.validate_vat_vies", "False"
            )
            != "True"
        ):
            return
        vat = self.supplier_vat
        if not vat:
            return
        from .vat_utils import check_vies_soap, split_country_vat

        country, _number = split_country_vat(vat)
        if not country:
            return
        status = None
        partner = self.partner_id
        if partner and hasattr(partner, "_check_vies_iap"):
            try:
                status = partner._check_vies_iap()
            except Exception as err:
                _logger.warning("IAP VIES failed for %s: %s", vat, err)
                status = None
            if status in ("invalid", "wrong", False):
                raise UserError(_("VIES (IAP) rejected supplier VAT %s.", vat))
            if status in ("valid", "verified", True):
                self.message_post(body=_("VIES (IAP) accepted supplier VAT %s.", vat))
                return
        valid = check_vies_soap(vat)
        if valid is False:
            raise UserError(_("VIES rejected supplier VAT %s.", vat))
        if valid is True:
            self.message_post(body=_("VIES accepted supplier VAT %s.", vat))
            return
        self.message_post(body=_(
            "VIES could not be reached for %s. Format check only.",
            vat,
        ))

    def _company_from_vat(self, company_vat, company_name=None, document_type=None):
        """Map document recipient NIF to an existing res.company."""
        companies = self.env["res.company"].sudo().search([])
        norm = self._normalize_vat(company_vat)
        if norm:
            hits = companies.filtered(lambda c: self._normalize_vat(c.vat) == norm)
            if len(hits) == 1:
                return hits
            if len(hits) > 1:
                raise UserError(_(
                    "Company VAT %s matches more than one company.",
                    company_vat,
                ))
            raise UserError(_(
                "Company VAT %s does not match any company.",
                company_vat,
            ))
        if company_name and len(companies) > 1:
            hits = companies.filtered(
                lambda c: (c.name or "").strip().lower() == company_name.strip().lower()
            )
            if len(hits) == 1:
                return hits
        if document_type in ("vendor_bill", "vendor_refund") and len(companies) > 1:
            raise UserError(_(
                "The bill has no company VAT and this database has several companies. "
                "Add company_vat / customer_vat / nif_destinatario to the Parseur template."
            ))
        return self.env.company

    def _identify_company(self):
        self.ensure_one()
        company = self._company_from_vat(
            self.company_vat,
            self.company_name_scan,
            document_type=self.document_type,
        )
        if company and company != self.company_id:
            self.company_id = company
        return company

    def _identify_partner(self):
        self.ensure_one()
        Partner = self.env['res.partner']
        partner = Partner.browse()
        vat = (self.supplier_vat or '').replace(' ', '').replace('-', '').upper()
        if vat:
            partners = Partner.search([
                ("vat", "=", vat),
                "|", ("company_id", "=", False), ("company_id", "=", self.company_id.id),
            ])
            if not partners:
                # Fallback: compare normalized VAT in Python to avoid ilike false positives.
                candidates = Partner.search([
                    ("vat", "!=", False),
                    "|", ("company_id", "=", False), ("company_id", "=", self.company_id.id),
                ], limit=80)
                partners = candidates.filtered(
                    lambda p: (p.vat or "").replace(" ", "").replace("-", "").upper() == vat
                )
            if len(partners) == 1:
                partner = partners
            elif len(partners) > 1:
                suppliers = partners.filtered(lambda p: p.supplier_rank)
                partner = suppliers[:1] if len(suppliers) == 1 else Partner.browse()
        if not partner and self.supplier_code:
            partner = Partner.search([
                ('ref', '=', self.supplier_code),
                '|', ('company_id', '=', False), ('company_id', '=', self.company_id.id),
            ], limit=1)
        name = self.supplier_name_corrected or self.supplier_name
        if not partner and name:
            partners = Partner.search([
                ('name', 'ilike', name.strip()),
                '|', ('company_id', '=', False), ('company_id', '=', self.company_id.id),
            ], limit=5)
            suppliers = partners.filtered(lambda p: p.supplier_rank or p.ref)
            if len(suppliers) == 1:
                partner = suppliers
            elif len(partners) == 1:
                partner = partners
        if not partner and name:
            suppliers = Partner.search([
                ("supplier_rank", ">", 0),
                "|", ("company_id", "=", False), ("company_id", "=", self.company_id.id),
            ], limit=80)
            partner = unique_fuzzy_match(suppliers, "name", name)
            if partner:
                _trace(self, "partner_fuzzy", partner=partner.id, raw=name)
        self.partner_id = partner

    def _match_purchase_orders(self):
        self.ensure_one()
        Purchase = self.env['purchase.order']
        domain_base = [
            ('company_id', '=', self.company_id.id),
            ('state', 'in', ('purchase', 'done', 'draft', 'sent')),
        ]
        candidates = Purchase.browse()
        if self.po_number:
            name = self.po_number.strip()
            candidates = Purchase.search(domain_base + ['|', ('name', '=', name), ('partner_ref', '=', name)])
            if not candidates:
                compact = normalize_text(name, ocr=False).replace(" ", "")
                open_pos = Purchase.search(domain_base, limit=80)
                hits = open_pos.browse()
                for po in open_pos:
                    if compact and compact in (
                        normalize_text(po.name, ocr=False).replace(" ", ""),
                        normalize_text(po.partner_ref or "", ocr=False).replace(" ", ""),
                    ):
                        hits |= po
                if len(hits) == 1:
                    candidates = hits
                    _trace(self, "po_fuzzy", purchase=hits.id, raw=name)
        if not candidates and self.partner_id:
            open_pos = Purchase.search(domain_base + [
                ('partner_id', 'child_of', self.partner_id.commercial_partner_id.id),
                ('state', 'in', ('purchase', 'draft', 'sent')),
            ], order='date_order desc', limit=20)
            product_ids = set(self.line_ids.product_id.ids)
            scored = []
            for po in open_pos:
                po_products = set(po.order_line.filtered(lambda l: not l.display_type).product_id.ids)
                overlap = len(product_ids & po_products)
                if overlap:
                    scored.append((overlap / max(len(product_ids), 1), po))
            scored.sort(key=lambda item: item[0], reverse=True)
            candidates = Purchase.browse([po.id for score, po in scored if score >= 0.5])
        self.candidate_purchase_ids = candidates
        if len(candidates) == 1:
            self.purchase_id = candidates
            self.match_score = 1.0
            self.line_ids._match_purchase_lines(self.purchase_id)
        elif len(candidates) > 1:
            self.purchase_id = False
            self.match_score = 0.5
        else:
            self.purchase_id = False
            self.match_score = 0.0

    def _set_exception(self, reason):
        self.write({'state': 'exception', 'exception_reason': reason})
        self.message_post(body=reason)

    # ------------------------------------------------------------------
    # Apply
    # ------------------------------------------------------------------
    def action_apply(self):
        errors = []
        for intake in self:
            try:
                with self.env.cr.savepoint():
                    intake = intake.with_company(intake.company_id)
                    if intake.state == "cancelled":
                        raise UserError(_("Cancelled documents cannot be applied."))
                    if intake.state == "applied":
                        continue
                    if intake.state not in ("identified", "matched", "exception", "draft"):
                        raise UserError(_("This document cannot be applied in its current state."))
                    if intake.state in ("draft", "exception"):
                        intake.action_identify()
                    intake._assert_price_decisions()
                    if intake.document_type == "delivery_note":
                        intake._apply_delivery_note()
                    elif intake.document_type == "return":
                        intake._apply_stock_return()
                    elif intake.document_type == "vendor_refund":
                        intake._apply_vendor_refund()
                    else:
                        intake._apply_vendor_bill()
            except UserError as err:
                intake._set_exception(str(err))
                errors.append("%s: %s" % (intake.display_name, err))
        if errors and len(self) == 1:
            raise UserError(errors[0].split(": ", 1)[-1])
        return True

    def _apply_price_exception_state(self):
        self.ensure_one()
        self.line_ids._compute_price_exceptions()
        ICP = self.env["ir.config_parameter"].sudo()
        over_policy = ICP.get_param("vendor_parseur_intake.over_policy", "exception")
        receipt_bad = self.line_ids.filtered(
            lambda l: l.match_status in ("over", "unordered", "unidentified")
        )
        if self.document_type == "delivery_note" and over_policy == "exception" and receipt_bad:
            details = ", ".join(
                "%s [%s] extra=%s" % (line.product_id.display_name, line.match_status, line.qty_extra)
                for line in receipt_bad
            )
            self._set_exception(_("Receipt exceptions pending review: %s", details))
            return
        pending = self.line_ids.filtered(lambda l: l.price_exception and l.price_decision == 'pending')
        if self.document_type == 'vendor_bill' and pending:
            details = ', '.join(
                '%s: %s → %s (%+.2f / %+.1f%%)' % (
                    line.product_id.display_name,
                    line.price_reference,
                    line.price_unit,
                    line.price_variance,
                    line.price_variance_pct,
                )
                for line in pending
            )
            self._set_exception(_('Price exceptions pending review: %s', details))
            return
        if self.purchase_id:
            self.state = 'matched'
            self.exception_reason = False
        else:
            self.state = 'identified'
            self.exception_reason = False

    def _assert_price_decisions(self):
        self.ensure_one()
        if self.document_type != 'vendor_bill':
            return
        pending = self.line_ids.filtered(lambda l: l.price_exception and l.price_decision == 'pending')
        if pending and self.price_decision == 'pending':
            raise UserError(_(
                'Resolve price exceptions first: accept the document price or keep the PO price.'
            ))

    def action_accept_document_prices(self):
        for intake in self:
            exceptions = intake.line_ids.filtered('price_exception')
            exceptions.write({'price_decision': 'accept_document'})
            intake.price_decision = 'accept_document'
            intake.message_post(body=_('Document prices accepted for %s line(s).', len(exceptions)))
            intake._refresh_after_price_decision()
        return True

    def action_keep_po_prices(self):
        for intake in self:
            exceptions = intake.line_ids.filtered('price_exception')
            exceptions.write({'price_decision': 'keep_po'})
            intake.price_decision = 'keep_po'
            intake.message_post(body=_('PO prices kept for %s line(s).', len(exceptions)))
            intake._refresh_after_price_decision()
        return True

    def _refresh_after_price_decision(self):
        for intake in self:
            intake._apply_price_exception_state()
        return True

    def action_review_price_exceptions(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Price exceptions"),
            "res_model": "vendor.document.intake.line",
            "view_mode": "list,form",
            "domain": [("intake_id", "=", self.id), ("price_exception", "=", True)],
            "target": "new",
            "context": {
                "default_intake_id": self.id,
                "create": False,
                "delete": False,
            },
        }

    def _apply_delivery_note(self):
        self.ensure_one()
        self._prepare_stock_validation()
        if not self.partner_id:
            raise UserError(_('Identify the vendor before applying the delivery note.'))
        if self.line_ids.filtered(lambda l: not l.product_id):
            raise UserError(_('Resolve unidentified products before receiving.'))

        ICP = self.env['ir.config_parameter'].sudo()
        over_policy = ICP.get_param('vendor_parseur_intake.over_policy', 'exception')
        auto_validate = bool(self.partner_id.tl_auto_validate_receipt)
        _trace(
            self,
            "apply_delivery_note",
            purchase=self.purchase_id.id,
            created_po=self.created_purchase,
            auto_validate=auto_validate,
            partner=self.partner_id.id,
        )

        if not self.purchase_id:
            self._create_purchase_from_receipt()
        else:
            self.line_ids._match_purchase_lines(self.purchase_id)
            self._assert_qty_policy(over_policy)

        if self.purchase_id.state in ('draft', 'sent'):
            self.purchase_id.button_confirm()

        picking = self._get_open_incoming_picking()
        if not picking:
            raise UserError(_('No incoming receipt found on purchase order %s.', self.purchase_id.name))
        self.picking_id = picking
        self._fill_picking_quantities(picking, over_policy)
        self._assign_corrected_lots(picking)
        if auto_validate:
            picking.with_context(skip_backorder=True, skip_sms=True).button_validate()
        self.state = 'applied'
        self.exception_reason = False
        self.message_post(body=_(
            'Delivery note applied on picking %s (PO %s).',
            picking.name, self.purchase_id.name,
        ))

    def _create_purchase_from_receipt(self):
        self.ensure_one()
        order_lines = []
        for line in self.line_ids.filtered(lambda l: l.product_id):
            qty = line.qty_document or 1.0
            price = line.price_unit
            if not price:
                seller = line.product_id._select_seller(
                    partner_id=self.partner_id,
                    quantity=qty,
                    date=self.document_date,
                    uom_id=line.product_id.uom_po_id,
                )
                price = seller.price if seller else 0.0
            order_lines.append(fields.Command.create({
                'product_id': line.product_id.id,
                'name': line.description or line.product_id.display_name,
                'product_qty': qty,
                'product_uom_id': line.product_id.uom_po_id.id,
                'price_unit': price,
                'date_planned': fields.Datetime.now(),
            }))
        po = self.env['purchase.order'].create({
            'partner_id': self.partner_id.id,
            'partner_ref': self.document_number or self.delivery_note_number or False,
            'origin': _('Parseur DN %s', self.name),
            'company_id': self.company_id.id,
            'currency_id': self.currency_id.id,
            'date_order': fields.Datetime.now(),
            'order_line': order_lines,
        })
        po.message_post(body=_(
            'Purchase order created from delivery note %s (phone / no prior PO).',
            self.document_number or self.name,
        ))
        self.purchase_id = po
        self.created_purchase = True
        self.line_ids._match_purchase_lines(po)
        return po

    def _get_open_incoming_picking(self):
        self.ensure_one()
        pickings = self.purchase_id.picking_ids.filtered(
            lambda p: p.state not in ('done', 'cancel') and p.picking_type_id.code == 'incoming'
        )
        return pickings[:1]

    def _assert_qty_policy(self, over_policy):
        self.ensure_one()
        precision = self.env['decimal.precision'].precision_get('Product Unit')
        tols = self.partner_id._tl_parseur_tolerances() if self.partner_id else {
            "qty_pct": 0.0, "qty_abs": 0.0,
        }

        def _is_over(line):
            if not line.purchase_line_id:
                return False
            remaining = max(
                line.purchase_line_id.product_qty - line.purchase_line_id.qty_received,
                0.0,
            )
            extra = line.qty_document - remaining
            if float_compare(extra, 0.0, precision_digits=precision) <= 0:
                return False
            threshold = max(tols["qty_abs"], remaining * tols["qty_pct"] / 100.0)
            return float_compare(extra, threshold, precision_digits=precision) > 0

        over_lines = self.line_ids.filtered(_is_over)
        unordered = self.line_ids.filtered(lambda l: l.product_id and not l.purchase_line_id)
        if over_policy == 'exception' and (over_lines or unordered):
            raise UserError(_(
                'Quantities exceed the purchase order or products are not on the PO: %s',
                ', '.join((over_lines | unordered).mapped(lambda l: l.product_id.display_name)),
            ))

    def _prepare_stock_validation(self):
        """Re-run spelling + product match before touching the picking."""
        self.ensure_one()
        if hasattr(self, "_run_spellcheck"):
            self._run_spellcheck()
        unidentified = self.line_ids.filtered(lambda l: not l.product_id)
        if unidentified:
            unidentified._identify_product()
        if self.purchase_id:
            self.line_ids._match_purchase_lines(self.purchase_id)
        self._correct_lots_for_stock()
        self._validate_expiry()
        self._assert_traceability()
        still_unknown = self.line_ids.filtered(lambda l: not l.product_id)
        if still_unknown:
            raise UserError(_(
                "Cannot validate stock: unidentified products after spellcheck: %s",
                ", ".join(
                    still_unknown.mapped(
                        lambda l: l.description_corrected or l.description or l.sku or "?"
                    )
                ),
            ))
        _trace(
            self,
            "stock_prepare",
            products=self.line_ids.mapped("product_id").ids,
            lots=self.line_ids.mapped("lot_id").ids,
            status=self.line_ids.mapped("match_status"),
        )

    def _split_lot_names(self, raw):
        if not raw:
            return []
        import re
        return [part.strip() for part in re.split(r"[,;/|\n]+", str(raw)) if part.strip()]

    def _min_shelf_life_days(self):
        partner_days = self.partner_id.tl_min_shelf_life_days if self.partner_id else 0
        if partner_days:
            return partner_days
        try:
            return int(
                self.env["ir.config_parameter"].sudo().get_param(
                    "vendor_parseur_intake.min_shelf_life_days", "0"
                )
                or 0
            )
        except ValueError:
            return 0

    def _validate_expiry(self):
        self.ensure_one()
        today = fields.Date.context_today(self)
        min_days = self._min_shelf_life_days()
        errors = []
        for line in self.line_ids.filtered("product_id"):
            expiry = line.expiry_date
            if not expiry and line.lot_id and "expiration_date" in line.lot_id._fields:
                expiry = line.lot_id.expiration_date
                if expiry and hasattr(expiry, "date"):
                    expiry = expiry.date()
                line.expiry_date = expiry
            uses_expiry = (
                line.product_id.use_expiration_date
                if "use_expiration_date" in line.product_id._fields
                else bool(expiry)
            )
            if not uses_expiry:
                line.expiry_state = "ok"
                continue
            if not expiry:
                line.expiry_state = "missing"
                errors.append(_("%s: missing expiry date", line.product_id.display_name))
                continue
            remaining = (expiry - today).days
            if remaining < 0:
                line.expiry_state = "expired"
                errors.append(_("%s expired on %s", line.product_id.display_name, expiry))
            elif min_days and remaining < min_days:
                line.expiry_state = "warning"
                errors.append(_(
                    "%s remaining life %s days < %s required",
                    line.product_id.display_name,
                    remaining,
                    min_days,
                ))
            else:
                line.expiry_state = "ok"
            if line.lot_id and expiry and "expiration_date" in line.lot_id._fields:
                try:
                    line.lot_id.expiration_date = expiry
                except Exception:
                    pass
        if errors:
            raise UserError(_("Expiry validation failed:\n%s") % "\n".join(errors))

    def _lot_domain(self, product):
        return [
            ("product_id", "=", product.id),
            "|",
            ("company_id", "=", False),
            ("company_id", "=", self.company_id.id),
        ]

    def _find_or_create_lot(self, product, name, create=True):
        Lot = self.env["stock.lot"]
        domain = self._lot_domain(product)
        lot = Lot.search(domain + [("name", "=", name)], limit=1)
        if lot:
            return lot, False
        from .text_utils import unique_fuzzy_match
        lot = unique_fuzzy_match(Lot.search(domain, limit=80), "name", name, threshold=0.92)
        if lot:
            return lot, False
        if not create:
            return Lot, False
        lot = Lot.create({
            "name": name,
            "product_id": product.id,
            "company_id": self.company_id.id,
        })
        return lot, True

    def _correct_lots_for_stock(self):
        """Resolve lots/serials from Parseur text, create missing lots on receipts."""
        self.ensure_one()
        create_missing = (
            self.env["ir.config_parameter"].sudo().get_param(
                "vendor_parseur_intake.create_lots", "True"
            )
            == "True"
        )
        notes = []
        for line in self.line_ids.filtered("product_id"):
            tracking = line.product_id.tracking
            names = self._split_lot_names(line.lot_corrected or line.lot_name)
            if tracking == "none":
                continue
            if tracking == "serial" and names and len(names) != int(line.qty_document or 0):
                if abs(len(names) - (line.qty_document or 0)) > 0 and line.qty_document:
                    notes.append(_(
                        "%s: %s serials for qty %s",
                        line.product_id.display_name,
                        len(names),
                        line.qty_document,
                    ))
            lots = self.env["stock.lot"]
            allow_create = create_missing and self.document_type == "delivery_note"
            for name in names:
                lot, created = self._find_or_create_lot(
                    line.product_id, name, create=allow_create
                )
                if lot:
                    lots |= lot
                    if created:
                        notes.append(_("Created lot %s for %s") % (lot.name, line.product_id.display_name))
                    elif lot.name != name:
                        notes.append(_("%s: %s → %s") % (line.product_id.display_name, name, lot.name))
            line.lot_ids = lots
            line.lot_id = lots[:1]
            if lots and not line.lot_corrected:
                line.lot_corrected = ", ".join(lots.mapped("name"))
        if notes:
            self.message_post(body=_("Traceability:<br/>%s") % "<br/>".join(notes))

    def _assert_traceability(self):
        self.ensure_one()
        missing = self.line_ids.filtered(
            lambda l: l.product_id
            and l.product_id.tracking in ("lot", "serial")
            and not l.lot_ids
            and not l.lot_id
            and not l.lot_name
        )
        if missing:
            raise UserError(_(
                "Tracked products without lot/serial on the document: %s",
                ", ".join(missing.mapped("product_id.display_name")),
            ))

    def _assign_corrected_lots(self, picking):
        self.ensure_one()
        self._assert_traceability()
        for line in self.line_ids.filtered(lambda l: l.product_id and (l.lot_ids or l.lot_id)):
            lots = line.lot_ids or line.lot_id
            moves = picking.move_ids.filtered(
                lambda m: m.product_id == line.product_id and m.state not in ("done", "cancel")
            )
            qty_left = abs(line.qty_document or 0.0)
            for move in moves:
                if "lot_ids" in move._fields:
                    move.lot_ids = [fields.Command.set(lots.ids)]
                if not move.move_line_ids:
                    move.with_context(skip_sms=True)._action_assign()
                move_lines = move.move_line_ids
                if line.product_id.tracking == "serial":
                    for lot, move_line in zip(lots, move_lines):
                        vals = {"lot_id": lot.id, "quantity": 1.0}
                        move_line.write(vals)
                else:
                    target = move_lines[:1]
                    if target:
                        vals = {
                            "lot_id": lots[:1].id,
                            "quantity": qty_left or target.quantity,
                        }
                        target.write(vals)
                    elif lots:
                        move.write({"lot_ids": [fields.Command.set(lots.ids)]})

    def _fill_picking_quantities(self, picking, over_policy):
        self.ensure_one()
        precision = self.env['decimal.precision'].precision_get('Product Unit')
        remaining_by_product = {}
        for line in self.line_ids.filtered('product_id'):
            remaining_by_product[line.product_id.id] = remaining_by_product.get(line.product_id.id, 0.0) + line.qty_document

        for move in picking.move_ids.filtered(lambda m: m.state not in ('done', 'cancel')):
            qty = remaining_by_product.get(move.product_id.id, 0.0)
            if float_is_zero(qty, precision_digits=precision):
                continue
            demand = move.product_uom_qty
            to_set = min(qty, demand) if over_policy == 'exception' else qty
            move.quantity = to_set
            remaining_by_product[move.product_id.id] = qty - to_set

        leftover = {pid: qty for pid, qty in remaining_by_product.items() if float_compare(qty, 0.0, precision_digits=precision) > 0}
        if leftover and over_policy == 'extend':
            self._extend_po_and_picking(picking, leftover)

    def _extend_po_and_picking(self, picking, leftover):
        self.ensure_one()
        for product_id, qty in leftover.items():
            product = self.env['product.product'].browse(product_id)
            intake_line = self.line_ids.filtered(lambda l: l.product_id.id == product_id)[:1]
            po_line = self.env['purchase.order.line'].create({
                'order_id': self.purchase_id.id,
                'product_id': product.id,
                'name': intake_line.description or product.display_name,
                'product_qty': qty,
                'product_uom_id': product.uom_po_id.id,
                'price_unit': intake_line.price_unit or 0.0,
                'date_planned': fields.Datetime.now(),
            })
            intake_line.purchase_line_id = po_line
        picking.action_assign()
        for product_id, qty in leftover.items():
            moves = picking.move_ids.filtered(
                lambda m: m.product_id.id == product_id and m.state not in ('done', 'cancel')
            )
            if moves:
                moves[:1].quantity = (moves[:1].quantity or 0.0) + qty

    def _normalize_return_quantities(self):
        self.ensure_one()
        lines = self.line_ids.filtered(lambda l: l.qty_document)
        if lines and all(line.qty_document < 0 for line in lines):
            if self.document_type == "delivery_note":
                self.document_type = "return"
            elif self.document_type == "vendor_bill":
                self.document_type = "vendor_refund"
        if self.document_type in ("return", "vendor_refund"):
            for line in self.line_ids:
                if line.qty_document < 0:
                    line.qty_document = abs(line.qty_document)

    def _done_incoming_picking(self):
        self.ensure_one()
        if self.picking_id and self.picking_id.state == "done":
            return self.picking_id
        pickings = self.purchase_id.picking_ids.filtered(
            lambda p: p.state == "done" and p.picking_type_id.code == "incoming"
        )
        return pickings[:1]

    def _apply_stock_return(self):
        self.ensure_one()
        self._prepare_stock_validation()
        if not self.purchase_id:
            raise UserError(_("Select the original purchase order before returning goods."))
        picking = self._done_incoming_picking()
        if not picking:
            raise UserError(_(
                "No validated receipt on %s. Receive the goods before processing the return.",
                self.purchase_id.name,
            ))
        Return = self.env["stock.return.picking"]
        wizard = Return.with_context(
            active_id=picking.id,
            active_ids=picking.ids,
            active_model="stock.picking",
        ).create({"picking_id": picking.id})
        if hasattr(wizard, "_onchange_picking_id"):
            wizard._onchange_picking_id()
        qty_by_product = {}
        for line in self.line_ids.filtered("product_id"):
            qty_by_product[line.product_id.id] = qty_by_product.get(line.product_id.id, 0.0) + abs(line.qty_document)
        return_lines = wizard.product_return_moves
        if return_lines:
            for wizard_line in return_lines:
                product = wizard_line.product_id
                wizard_line.quantity = qty_by_product.get(product.id, 0.0)
                if "to_refund" in wizard_line._fields:
                    wizard_line.to_refund = True
        action = wizard.action_create_returns()
        return_picking = self.env["stock.picking"]
        if isinstance(action, dict) and action.get("res_id"):
            return_picking = self.env["stock.picking"].browse(action["res_id"])
        if not return_picking:
            return_picking = picking.returned_ids[:1] if "returned_ids" in picking._fields else picking.search([
                ("origin", "ilike", picking.name),
                ("picking_type_id.code", "=", "outgoing"),
            ], limit=1, order="id desc")
        if not return_picking:
            raise UserError(_("Odoo did not create the return picking from %s.", picking.name))
        auto_validate = bool(self.partner_id.tl_auto_validate_receipt)
        if auto_validate and return_picking.state != "done":
            return_picking.with_context(skip_backorder=True, skip_sms=True).button_validate()
        self.return_picking_id = return_picking
        self.picking_id = picking
        self.state = "applied"
        self.exception_reason = False
        self.message_post(body=_(
            "Vendor return %s created from receipt %s.",
            return_picking.name,
            picking.name,
        ))
        _trace(self, "stock_return", return_picking=return_picking.id, source=picking.id)

    def _apply_vendor_refund(self):
        self.ensure_one()
        if not self.purchase_id:
            raise UserError(_("Select the original purchase order before creating a refund."))
        if not self.return_picking_id and self._done_incoming_picking():
            try:
                self._apply_stock_return()
            except UserError:
                _logger.info("Refund without stock return on %s", self.name)
        invoices = self.purchase_id.invoice_ids.filtered(
            lambda m: m.move_type == "in_invoice" and m.state == "posted"
        )
        if invoices:
            refund = invoices[:1]._reverse_moves()
            refund = refund[:1] if refund else self.env["account.move"]
        else:
            action = self.purchase_id.with_company(self.company_id).action_create_invoice()
            refund = self.purchase_id.invoice_ids.filtered(lambda m: m.move_type == "in_refund")[:1]
            if not refund and action and action.get("res_id"):
                refund = self.env["account.move"].browse(action["res_id"])
        if not refund:
            raise UserError(_("Could not create a vendor refund from purchase order %s.", self.purchase_id.name))
        ref = self.invoice_number or self.document_number
        vals = {"move_type": refund.move_type}
        if ref:
            vals["ref"] = ref
        if self.document_date:
            vals["invoice_date"] = self.document_date
        refund.write({k: v for k, v in vals.items() if k != "move_type" or refund.move_type != "in_invoice"})
        self.invoice_id = refund
        self.state = "applied"
        self.exception_reason = False
        self.message_post(body=_("Vendor refund %s created from Parseur.", refund.name or refund.id))

    def _apply_vendor_bill(self):
        self.ensure_one()
        if not self.partner_id:
            raise UserError(_('Identify the vendor before creating the bill.'))
        if not self.purchase_id:
            raise UserError(_(
                'No purchase order found for this bill. Process the delivery note first '
                'or select a PO manually.'
            ))
        if self.purchase_id.state in ('draft', 'sent'):
            raise UserError(_('Confirm the purchase order before invoicing.'))

        precision = self.env['decimal.precision'].precision_get('Product Unit')
        if all(float_is_zero(line.qty_received, precision_digits=precision) for line in self.purchase_id.order_line if not line.display_type):
            raise UserError(_(
                'Nothing has been received on %s. Wait for the delivery note before invoicing goods.',
                self.purchase_id.name,
            ))

        invoices_before = self.purchase_id.invoice_ids
        action = self.purchase_id.with_company(self.company_id).action_create_invoice()
        invoice = self.purchase_id.invoice_ids - invoices_before
        if not invoice and action and action.get('res_id'):
            invoice = self.env['account.move'].browse(action['res_id'])
        if not invoice:
            invoice = self.purchase_id.invoice_ids[:1]
        if not invoice:
            raise UserError(_('Odoo did not create a vendor bill. Check the billing control policy.'))
        invoice = invoice[:1]
        ref = self.invoice_number or self.document_number
        vals = {}
        if ref:
            vals['ref'] = ref
        if self.document_date:
            vals['invoice_date'] = self.document_date
        if vals:
            invoice.write(vals)
        self._apply_price_decision_on_invoice(invoice)
        self.invoice_id = invoice
        self._maybe_auto_post_bill(invoice)
        self.state = 'applied'
        self.exception_reason = False
        posted = invoice.state == "posted"
        self.message_post(body=_(
            "%s vendor bill %s created from Parseur.",
            _("Posted") if posted else _("Draft"),
            invoice.name or invoice.id,
        ))

    def _maybe_auto_post_bill(self, invoice):
        self.ensure_one()
        ICP = self.env["ir.config_parameter"].sudo()
        if ICP.get_param("vendor_parseur_intake.auto_post_bill", "False") != "True":
            return
        if self.has_pending_price_exception:
            return
        try:
            tol_pct = float(ICP.get_param("vendor_parseur_intake.bill_total_tolerance_pct", "1.0") or 1.0)
            tol_abs = float(ICP.get_param("vendor_parseur_intake.bill_total_tolerance_abs", "0.05") or 0.05)
        except ValueError:
            tol_pct, tol_abs = 1.0, 0.05
        document_total = self.amount_total or 0.0
        invoice_total = invoice.amount_total or 0.0
        if document_total:
            delta = abs(invoice_total - document_total)
            threshold = max(tol_abs, abs(document_total) * tol_pct / 100.0)
            if delta > threshold:
                self.message_post(body=_(
                    "Bill not posted: total %s vs document %s (tolerance %s).",
                    invoice_total,
                    document_total,
                    threshold,
                ))
                return
        try:
            invoice.action_post()
        except UserError as err:
            self.message_post(body=_("Bill left in draft: %s", err))

    def _line_price_decision(self, line):
        if not line.price_exception:
            return "keep_po"
        if line.price_decision != "pending":
            return line.price_decision
        if self.price_decision != "pending":
            return self.price_decision
        return "pending"

    def _apply_price_decision_on_invoice(self, invoice):
        self.ensure_one()
        ICP = self.env['ir.config_parameter'].sudo()
        update_po = ICP.get_param('vendor_parseur_intake.update_po_price', 'False') == 'True'
        diff_mode = ICP.get_param('vendor_parseur_intake.price_diff_mode', 'rewrite_line')
        notes = []
        extra_commands = []
        for line in self.line_ids.filtered(lambda l: l.product_id):
            decision = self._line_price_decision(line)
            if decision != "accept_document" or not line.price_exception:
                continue
            qty = line.qty_document or 1.0
            delta = line.price_variance * qty
            notes.append(
                _("%(product)s: PO %(po).4f → bill %(bill).4f, qty %(qty)s, delta %(delta).2f")
                % {
                    "product": line.product_id.display_name,
                    "po": line.price_reference,
                    "bill": line.price_unit,
                    "qty": qty,
                    "delta": delta,
                }
            )
            inv_lines = invoice.invoice_line_ids.filtered(
                lambda aml: aml.purchase_line_id == line.purchase_line_id
                or (aml.product_id == line.product_id and aml.display_type == "product")
            )
            if diff_mode == "extra_line":
                account = inv_lines[:1].account_id
                if not account and line.product_id:
                    accounts = line.product_id.product_tmpl_id.get_product_accounts()
                    account = accounts.get("expense")
                if not account:
                    raise UserError(_(
                        "No expense account for price difference on %s.",
                        line.product_id.display_name,
                    ))
                extra_commands.append(
                    fields.Command.create(
                        {
                            "name": _("Price difference %s (PO %.4f → %.4f)")
                            % (line.product_id.display_name, line.price_reference, line.price_unit),
                            "quantity": 1.0,
                            "price_unit": delta,
                            "account_id": account.id,
                            "product_id": False,
                        }
                    )
                )
            elif inv_lines and line.price_unit:
                inv_lines.write({"price_unit": line.price_unit})
            if update_po and line.purchase_line_id and line.price_unit:
                try:
                    line.purchase_line_id.write({"price_unit": line.price_unit})
                except UserError:
                    _logger.info("Could not update PO line price on %s", self.purchase_id.name)
        if extra_commands:
            invoice.write({"invoice_line_ids": extra_commands})
        if notes:
            self.message_post(body=_("Price differences applied:<br/>%s") % "<br/>".join(notes))
            invoice.message_post(body=_("Price differences from Parseur:<br/>%s") % "<br/>".join(notes))

    def action_retry_related(self):
        """Re-run matching when the sibling document (DN or bill) arrives later."""
        self.action_identify()
        return True

    def action_cancel(self):
        self.write({'state': 'cancelled'})
        return True

    def action_reset_draft(self):
        self.write({'state': 'draft', 'exception_reason': False})
        return True

    def on_barcode_scanned(self, barcode):
        self.ensure_one()
        return self._process_scanned_barcode(barcode)

    def action_process_scanned_barcode(self):
        self.ensure_one()
        if not self.last_scanned_barcode:
            raise UserError(_("Scan or type a barcode first."))
        return self._process_scanned_barcode(self.last_scanned_barcode)

    def _process_scanned_barcode(self, barcode):
        self.ensure_one()
        code = (barcode or "").strip().strip("\r").strip("\n")
        ICP = self.env["ir.config_parameter"].sudo()
        prefix = ICP.get_param("vendor_parseur_intake.barcode_prefix") or ""
        if prefix and code.startswith(prefix):
            code = code[len(prefix):]
        try:
            min_len = int(ICP.get_param("vendor_parseur_intake.barcode_min_length", "3") or 3)
        except ValueError:
            min_len = 3
        if not code or len(code) < min_len:
            self.scan_message = _("Scan ignored (too short): %s", code)
            return True
        self.last_scanned_barcode = code
        from .qr_utils import looks_like_qr, parse_qr_payload
        qr_data = parse_qr_payload(code)
        if looks_like_qr(code) or qr_data.get("kind") != "plain":
            ok, message = self._validate_qr_payload(qr_data)
            if not ok:
                self.scan_message = message
                self.message_post(body=message)
                _trace(self, "qr_rejected", code=code, data=qr_data)
                raise UserError(message)
            code = str(qr_data.get("code") or code)
            if qr_data.get("lot") or qr_data.get("serial"):
                self._assign_qr_lot(qr_data)
            if qr_data.get("po") and not self.purchase_id:
                po = self.env["purchase.order"].search([
                    ("name", "=", qr_data["po"]),
                    ("company_id", "=", self.company_id.id),
                ], limit=1)
                if po:
                    self.purchase_id = po
            self.last_scanned_barcode = code
        Product = self.env["product.product"]
        Lot = self.env["stock.lot"]
        Purchase = self.env["purchase.order"]

        product = Product.search(
            ["|", ("barcode", "=", code), ("default_code", "=", code)], limit=1
        )
        if product:
            line = self.line_ids.filtered(lambda l: l.product_id == product)[:1]
            if not line:
                line = self.line_ids.filtered(
                    lambda l: (l.sku or l.barcode or l.sku_corrected) == code
                )[:1]
            if line:
                line.product_id = product
                line.barcode = code
                if line.match_status == "unidentified":
                    line.match_status = "pending"
                self.scan_message = _("Product confirmed: %s", product.display_name)
            else:
                self.env["vendor.document.intake.line"].create({
                    "intake_id": self.id,
                    "barcode": code,
                    "sku": product.default_code,
                    "product_id": product.id,
                    "qty_document": 1.0,
                    "description": product.display_name,
                })
                self.scan_message = _("Added scanned product %s", product.display_name)
            self.message_post(body=self.scan_message)
            _trace(self, "barcode_product", code=code, product=product.id)
            return True

        lot = Lot.search([("name", "=", code)], limit=1)
        if not lot and self.line_ids.product_id:
            lot = Lot.search([
                ("name", "=", code),
                ("product_id", "in", self.line_ids.product_id.ids),
            ], limit=1)
        if lot:
            line = self.line_ids.filtered(lambda l: l.product_id == lot.product_id)[:1]
            if not line:
                line = self.line_ids.filtered(lambda l: not l.lot_id)[:1]
            if line:
                line.lot_id = lot
                line.lot_ids = [fields.Command.link(lot.id)]
                line.lot_name = line.lot_name or lot.name
                line.product_id = line.product_id or lot.product_id
                self.scan_message = _("Lot %s assigned to %s", lot.name, line.product_id.display_name)
                self.message_post(body=self.scan_message)
                _trace(self, "barcode_lot", code=code, lot=lot.id)
                return True

        purchase = Purchase.search([
            "|", ("name", "=", code), ("partner_ref", "=", code),
            ("company_id", "=", self.company_id.id),
        ], limit=1)
        if purchase:
            self.purchase_id = purchase
            self.po_number = purchase.name
            self.line_ids._match_purchase_lines(purchase)
            self.scan_message = _("Purchase order %s linked", purchase.name)
            self.message_post(body=self.scan_message)
            _trace(self, "barcode_po", code=code, purchase=purchase.id)
            return True

        self.scan_message = _("Unknown barcode: %s", code)
        _trace(self, "barcode_unknown", code=code)
        return True

    def _validate_qr_payload(self, qr_data):
        self.ensure_one()
        ICP = self.env["ir.config_parameter"].sudo()
        if ICP.get_param("vendor_parseur_intake.validate_qr", "True") != "True":
            return True, _("QR accepted without validation")
        code = str(qr_data.get("code") or qr_data.get("gtin") or qr_data.get("sku") or "")
        gtin = str(qr_data.get("gtin") or "")
        sku = str(qr_data.get("sku") or "")
        Product = self.env["product.product"]
        product = Product.search(
            [
                "|", "|", "|",
                ("barcode", "=", code),
                ("barcode", "=", gtin),
                ("default_code", "=", sku or code),
                ("barcode", "=", sku),
            ],
            limit=1,
        )
        if gtin and len(gtin) in (8, 12, 13, 14) and not product:
            return False, _("QR GTIN %s is not a known product barcode.", gtin)
        if self.line_ids.product_id and product and product not in self.line_ids.product_id:
            return False, _(
                "QR product %s is not on this document.",
                product.display_name,
            )
        doc = str(qr_data.get("document") or qr_data.get("albaran") or qr_data.get("ref") or "")
        if doc and self.document_number and doc != self.document_number:
            return False, _("QR document %s does not match %s.", doc, self.document_number)
        po_name = str(qr_data.get("po") or "")
        if po_name and self.purchase_id and po_name != self.purchase_id.name:
            return False, _("QR order %s does not match %s.", po_name, self.purchase_id.name)
        if qr_data.get("kind") == "url":
            raw = qr_data.get("raw") or ""
            allowed = ICP.get_param("vendor_parseur_intake.qr_allowed_hosts") or ""
            if allowed:
                from urllib.parse import urlparse
                host = urlparse(raw).netloc.lower()
                hosts = [h.strip().lower() for h in allowed.split(",") if h.strip()]
                if host and hosts and host not in hosts:
                    return False, _("QR host %s is not allowed.", host)
        return True, _("QR validated (%s)", qr_data.get("kind"))

    def _assign_qr_lot(self, qr_data):
        name = qr_data.get("lot") or qr_data.get("serial")
        if not name:
            return
        product = False
        gtin = qr_data.get("gtin") or qr_data.get("code")
        if gtin:
            product = self.env["product.product"].search(
                ["|", ("barcode", "=", gtin), ("default_code", "=", gtin)], limit=1
            )
        line = self.line_ids.filtered(lambda l: product and l.product_id == product)[:1]
        line = line or self.line_ids[:1]
        if not line:
            return
        lot, _created = self._find_or_create_lot(
            line.product_id or product,
            name,
            create=self.document_type == "delivery_note",
        )
        if lot:
            line.lot_id = lot
            line.lot_ids = [fields.Command.link(lot.id)]
            line.lot_name = line.lot_name or name
        from .qr_utils import parse_expiry_value
        expiry = parse_expiry_value(qr_data.get("expiry") or qr_data.get("best_before"))
        if expiry:
            line.expiry_date = expiry
            if lot and "expiration_date" in lot._fields:
                lot.expiration_date = expiry

    def action_view_purchase(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'purchase.order',
            'res_id': self.purchase_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_view_picking(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'stock.picking',
            'res_id': self.picking_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_view_return_picking(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "stock.picking",
            "res_id": self.return_picking_id.id,
            "view_mode": "form",
            "target": "current",
        }

    def action_view_invoice(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'res_id': self.invoice_id.id,
            'view_mode': 'form',
            'target': 'current',
        }
