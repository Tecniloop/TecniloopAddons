# -*- coding: utf-8 -*-
from odoo import fields, models
from odoo.tools import float_compare, float_is_zero

from .text_utils import unique_fuzzy_match


class VendorDocumentIntakeLine(models.Model):
    _name = 'vendor.document.intake.line'
    _description = 'Vendor document intake line'
    _order = 'sequence, id'

    intake_id = fields.Many2one(
        'vendor.document.intake', required=True, ondelete='cascade', index=True,
    )
    company_id = fields.Many2one(related='intake_id.company_id', store=True)
    sequence = fields.Integer(default=10)
    sku = fields.Char()
    sku_corrected = fields.Char()
    supplier_code = fields.Char()
    barcode = fields.Char()
    description = fields.Char()
    description_corrected = fields.Char()
    qty_document = fields.Float(digits='Product Unit')
    uom_name = fields.Char()
    price_unit = fields.Float(digits='Product Price')
    price_subtotal = fields.Float(digits='Product Price')
    lot_name = fields.Char()
    lot_corrected = fields.Char()
    lot_id = fields.Many2one("stock.lot")
    lot_ids = fields.Many2many("stock.lot", string="Lots / serials")
    tracking = fields.Selection(related="product_id.tracking", readonly=True)
    expiry_date = fields.Date()
    expiry_state = fields.Selection(
        [
            ("ok", "OK"),
            ("warning", "Short shelf life"),
            ("expired", "Expired"),
            ("missing", "Missing"),
        ],
        default="ok",
    )

    product_id = fields.Many2one('product.product')
    purchase_line_id = fields.Many2one('purchase.order.line', check_company=True)
    match_status = fields.Selection(
        [
            ('pending', 'Pending'),
            ('ok', 'OK'),
            ('under', 'Under ordered'),
            ('over', 'Over ordered'),
            ('unordered', 'Not on PO'),
            ('unidentified', 'Unidentified'),
        ],
        default='pending',
    )
    qty_ordered = fields.Float(digits='Product Unit')
    qty_received = fields.Float(digits='Product Unit')
    qty_remaining = fields.Float(digits='Product Unit')
    qty_extra = fields.Float(digits='Product Unit')
    price_reference = fields.Float(string='PO / tariff price', digits='Product Price')
    price_variance = fields.Float(digits='Product Price')
    price_variance_pct = fields.Float(string='Variance %')
    price_exception = fields.Boolean()
    price_decision = fields.Selection(
        [
            ('pending', 'Pending'),
            ('accept_document', 'Accept document price'),
            ('keep_po', 'Keep PO price'),
        ],
        default='pending',
    )

    def _identify_product(self):
        Product = self.env['product.product']
        SupplierInfo = self.env['product.supplierinfo']
        partner = self.mapped('intake_id.partner_id')[:1]
        for line in self:
            product = Product.browse()
            if line.barcode:
                product = Product.search([('barcode', '=', line.barcode)], limit=1)
            sku = line.sku_corrected or line.sku
            description = line.description_corrected or line.description
            if not product and sku:
                product = Product.search(['|', ('default_code', '=', sku), ('barcode', '=', sku)], limit=1)
            if not product and (line.supplier_code or sku) and partner:
                info = SupplierInfo.search([
                    ('partner_id', 'child_of', partner.commercial_partner_id.id),
                    ('product_code', '=', line.supplier_code or sku),
                ], limit=1)
                product = info.product_id or info.product_tmpl_id.product_variant_id
            if not product and description and partner:
                info = SupplierInfo.search([
                    ('partner_id', 'child_of', partner.commercial_partner_id.id),
                    ('product_name', 'ilike', description.strip()),
                ], limit=2)
                if len(info) == 1:
                    product = info.product_id or info.product_tmpl_id.product_variant_id
            if not product and description:
                products = Product.search([('name', 'ilike', description.strip())], limit=2)
                if len(products) == 1:
                    product = products
            if not product and description:
                if partner:
                    infos = SupplierInfo.search([
                        ("partner_id", "child_of", partner.commercial_partner_id.id),
                    ], limit=80)
                    info = unique_fuzzy_match(infos, "product_name", description)
                    if info:
                        product = info.product_id or info.product_tmpl_id.product_variant_id
                if not product:
                    pool = Product.search([("purchase_ok", "=", True)], limit=80)
                    product = unique_fuzzy_match(pool, "name", description)
            line.product_id = product
            if not product:
                line.match_status = 'unidentified'

    def _match_purchase_lines(self, purchase):
        precision = self.env['decimal.precision'].precision_get('Product Unit')
        used = self.env['purchase.order.line']
        for line in self:
            po_line = line.purchase_line_id
            if not po_line or po_line.order_id != purchase:
                candidates = purchase.order_line.filtered(
                    lambda l: not l.display_type and l.product_id == line.product_id and l not in used
                )
                po_line = candidates[:1]
            line.purchase_line_id = po_line
            if po_line:
                used |= po_line
                line.qty_ordered = po_line.product_qty
                line.qty_received = po_line.qty_received
                remaining = max(po_line.product_qty - po_line.qty_received, 0.0)
                extra = line.qty_document - remaining
                line.qty_remaining = remaining
                line.qty_extra = extra
                if float_compare(extra, 0.0, precision_digits=precision) > 0:
                    tols = line.intake_id.partner_id._tl_parseur_tolerances() if line.intake_id.partner_id else {
                        "qty_pct": 0.0, "qty_abs": 0.0,
                    }
                    threshold = max(tols["qty_abs"], remaining * tols["qty_pct"] / 100.0)
                    if float_compare(extra, threshold, precision_digits=precision) > 0:
                        line.match_status = "over"
                    else:
                        line.match_status = "ok"
                elif float_compare(line.qty_document, remaining, precision_digits=precision) < 0:
                    line.match_status = "under"
                else:
                    line.match_status = "ok"
            elif line.product_id:
                line.match_status = 'unordered'
                line.qty_ordered = 0.0
                line.qty_received = 0.0
            else:
                line.match_status = 'unidentified'
        self._compute_price_exceptions()

    def _reference_price(self):
        self.ensure_one()
        if self.purchase_line_id:
            po_line = self.purchase_line_id
            return po_line.price_unit_discounted if 'price_unit_discounted' in po_line._fields else po_line.price_unit
        product = self.product_id
        partner = self.intake_id.partner_id
        if not product:
            return 0.0
        seller = product._select_seller(
            partner_id=partner,
            quantity=self.qty_document or 1.0,
            date=self.intake_id.document_date,
            uom_id=product.uom_po_id,
        )
        return seller.price if seller else 0.0

    def action_accept_document_price(self):
        self.write({"price_decision": "accept_document"})
        self.mapped("intake_id")._refresh_after_price_decision()
        return True

    def action_keep_po_price(self):
        self.write({"price_decision": "keep_po"})
        self.mapped("intake_id")._refresh_after_price_decision()
        return True

    def _tolerance_values(self):
        self.ensure_one()
        partner = self.intake_id.partner_id
        if partner:
            values = partner._tl_parseur_tolerances()
            return values["price_pct"], values["price_abs"]
        return 2.0, 0.05

    def _compute_price_exceptions(self):
        prec = self.env['decimal.precision'].precision_get('Product Price')
        for line in self:
            tol_pct, tol_abs = line._tolerance_values() if line.intake_id else (2.0, 0.05)
            reference = line._reference_price()
            document_price = line.price_unit
            if float_is_zero(document_price, precision_digits=prec) and line.qty_document:
                document_price = line.price_subtotal / line.qty_document if line.qty_document else 0.0
            variance = document_price - reference
            pct = (variance / reference * 100.0) if reference else (100.0 if document_price else 0.0)
            threshold = max(tol_abs, abs(reference) * tol_pct / 100.0)
            is_exc = float_compare(abs(variance), threshold, precision_digits=prec) > 0 and not float_is_zero(document_price or reference, precision_digits=prec)
            # Ignore tiny noise when both prices are zero
            if float_is_zero(document_price, precision_digits=prec) and float_is_zero(reference, precision_digits=prec):
                is_exc = False
            line.price_reference = reference
            line.price_variance = variance
            line.price_variance_pct = pct
            line.price_exception = is_exc


def _to_float_param(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
