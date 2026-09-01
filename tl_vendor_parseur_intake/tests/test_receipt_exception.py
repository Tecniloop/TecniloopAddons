# Copyright 2026 Tecniloop
# License Other proprietary.

from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestReceiptException(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["ir.config_parameter"].sudo().set_param(
            "vendor_parseur_intake.validate_vat_format", "False"
        )
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.env["ir.config_parameter"].sudo().set_param(
            "vendor_parseur_intake.over_policy", "exception"
        )
        cls.partner = cls.env["res.partner"].create(
            {
                "name": "Receipt Vendor",
                "vat": "ESC1234567Z",
                "supplier_rank": 1,
                "tl_qty_tolerance_pct": 0.0,
                "tl_qty_tolerance_abs": 0.0,
            }
        )
        cls.product = cls.env["product.product"].create(
            {
                "name": "Pine board",
                "default_code": "PINE-01",
                "is_storable": True,
                "purchase_ok": True,
            }
        )
        cls.extra = cls.env["product.product"].create(
            {
                "name": "Extra item",
                "default_code": "EXTRA-01",
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
                            "product_qty": 10,
                            "product_uom_id": cls.product.uom_po_id.id,
                            "price_unit": 5.0,
                        },
                    )
                ],
            }
        )
        cls.po.button_confirm()
        cls.Intake = cls.env["vendor.document.intake"]

    def test_over_qty_is_receipt_exception(self):
        intake = self.Intake.ingest_parseur_payload(
            {
                "document_type": "albaran",
                "supplier_vat": "ESC1234567Z",
                "po_number": self.po.name,
                "document_number": "ALB-OVER",
                "items": [{"sku": "PINE-01", "qty": 13}],
            }
        )
        self.assertEqual(intake.line_ids.match_status, "over")
        self.assertEqual(intake.receipt_exception_count, 1)
        self.assertEqual(intake.state, "exception")
        with self.assertRaises(UserError):
            intake.action_apply()

    def test_qty_within_partner_tolerance_is_ok(self):
        self.partner.tl_qty_tolerance_abs = 5.0
        intake = self.Intake.ingest_parseur_payload(
            {
                "document_type": "albaran",
                "supplier_vat": "ESC1234567Z",
                "po_number": self.po.name,
                "document_number": "ALB-TOL",
                "items": [{"sku": "PINE-01", "qty": 13}],
            }
        )
        self.assertEqual(intake.line_ids.match_status, "ok")
        self.assertEqual(intake.receipt_exception_count, 0)
        self.assertNotEqual(intake.state, "exception")

    def test_unordered_product_is_receipt_exception(self):
        intake = self.Intake.ingest_parseur_payload(
            {
                "document_type": "albaran",
                "supplier_vat": "ESC1234567Z",
                "po_number": self.po.name,
                "document_number": "ALB-UNORD",
                "items": [
                    {"sku": "PINE-01", "qty": 10},
                    {"sku": "EXTRA-01", "qty": 1},
                ],
            }
        )
        extra_line = intake.line_ids.filtered(lambda l: l.product_id == self.extra)
        self.assertEqual(extra_line.match_status, "unordered")
        self.assertGreaterEqual(intake.receipt_exception_count, 1)
        self.assertEqual(intake.state, "exception")

    def test_partial_receipt_is_under_not_exception(self):
        intake = self.Intake.ingest_parseur_payload(
            {
                "document_type": "albaran",
                "supplier_vat": "ESC1234567Z",
                "po_number": self.po.name,
                "document_number": "ALB-UNDER",
                "items": [{"sku": "PINE-01", "qty": 4}],
            }
        )
        self.assertEqual(intake.line_ids.match_status, "under")
        self.assertEqual(intake.receipt_exception_count, 0)
        self.assertNotEqual(intake.state, "exception")
