# Copyright 2026 Tecniloop
# License Other proprietary.

from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestPriceException(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["ir.config_parameter"].sudo().set_param(
            "vendor_parseur_intake.validate_vat_format", "False"
        )
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.env["ir.config_parameter"].sudo().set_param(
            "vendor_parseur_intake.price_tolerance_pct", "1.0"
        )
        cls.env["ir.config_parameter"].sudo().set_param(
            "vendor_parseur_intake.price_tolerance_abs", "0.01"
        )
        cls.partner = cls.env["res.partner"].create(
            {"name": "Price Vendor", "vat": "ESB1234567X", "supplier_rank": 1}
        )
        cls.product = cls.env["product.product"].create(
            {
                "name": "Steel bar",
                "default_code": "STL-01",
                "is_storable": True,
                "purchase_ok": True,
            }
        )
        cls.po = cls.env["purchase.order"].create(
            {
                "partner_id": cls.partner.id,
                "order_line": [
                    (
                        0,
                        0,
                        {
                            "product_id": cls.product.id,
                            "product_qty": 2,
                            "product_uom_id": cls.product.uom_po_id.id,
                            "price_unit": 10.0,
                        },
                    )
                ],
            }
        )
        cls.po.button_confirm()
        picking = cls.po.picking_ids.filtered(
            lambda p: p.picking_type_id.code == "incoming"
        )[:1]
        for move in picking.move_ids:
            move.quantity = move.product_uom_qty
        picking.with_context(skip_backorder=True, skip_sms=True).button_validate()

    def test_price_exception_blocks_apply(self):
        intake = self.env["vendor.document.intake"].ingest_parseur_payload(
            {
                "document_type": "factura",
                "supplier_vat": "ESB1234567X",
                "po_number": self.po.name,
                "invoice_number": "F-1",
                "items": [{"sku": "STL-01", "qty": 2, "unit_price": 15.0}],
            }
        )
        self.assertEqual(intake.state, "exception")
        self.assertTrue(intake.line_ids.price_exception)
        with self.assertRaises(UserError):
            intake.action_apply()
        intake.action_keep_po_prices()
        intake.action_apply()
        self.assertEqual(intake.state, "applied")
        self.assertTrue(intake.invoice_id)
        self.assertEqual(intake.invoice_id.state, "draft")

    def test_partner_tolerance_skips_small_gap(self):
        self.partner.tl_price_tolerance_pct = 80.0
        intake = self.env["vendor.document.intake"].ingest_parseur_payload(
            {
                "document_type": "factura",
                "supplier_vat": "ESB1234567X",
                "po_number": self.po.name,
                "invoice_number": "F-2",
                "items": [{"sku": "STL-01", "qty": 2, "unit_price": 15.0}],
            }
        )
        self.assertFalse(intake.line_ids.price_exception)
        self.assertNotEqual(intake.state, "exception")

    def test_line_level_accept_document_price(self):
        intake = self.env["vendor.document.intake"].ingest_parseur_payload(
            {
                "document_type": "factura",
                "supplier_vat": "ESB1234567X",
                "po_number": self.po.name,
                "invoice_number": "F-3",
                "items": [{"sku": "STL-01", "qty": 2, "unit_price": 15.0}],
            }
        )
        intake.line_ids.action_accept_document_price()
        self.assertEqual(intake.line_ids.price_decision, "accept_document")
        self.assertFalse(intake.has_pending_price_exception)
