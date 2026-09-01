# Copyright 2026 Tecniloop
# License Other proprietary.

from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestVendorParseurIntake(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["ir.config_parameter"].sudo().set_param(
            "vendor_parseur_intake.validate_vat_format", "False"
        )
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.partner = cls.env["res.partner"].create(
            {
                "name": "ACME Supplier",
                "vat": "ESA12345674",
                "supplier_rank": 1,
                "tl_auto_validate_receipt": False,
            }
        )
        cls.product = cls.env["product.product"].create(
            {
                "name": "Oak board",
                "default_code": "WOOD-01",
                "is_storable": True,
                "purchase_ok": True,
                "list_price": 12.5,
                "standard_price": 10.0,
            }
        )
        cls.Intake = cls.env["vendor.document.intake"]

    def test_ingest_delivery_note_creates_po_when_missing(self):
        intake = self.Intake.ingest_parseur_payload(
            {
                "document_type": "albaran",
                "supplier_vat": "ESA12345674",
                "document_number": "ALB-88",
                "items": [{"sku": "WOOD-01", "qty": 4, "unit_price": 12.5}],
            }
        )
        self.assertEqual(intake.document_type, "delivery_note")
        self.assertEqual(intake.partner_id, self.partner)
        self.assertEqual(intake.line_ids.product_id, self.product)
        self.assertFalse(intake.purchase_id)
        self.assertEqual(intake.state, "identified")
        intake.action_apply()
        self.assertTrue(intake.created_purchase)
        self.assertEqual(intake.purchase_id.partner_id, self.partner)
        self.assertEqual(intake.state, "applied")
        self.assertTrue(intake.picking_id)
        self.assertNotEqual(intake.picking_id.state, "done")

    def test_partner_auto_validate_receipt(self):
        self.partner.tl_auto_validate_receipt = True
        po = self.env["purchase.order"].create(
            {
                "partner_id": self.partner.id,
                "order_line": [
                    (
                        0,
                        0,
                        {
                            "product_id": self.product.id,
                            "product_qty": 4,
                            "product_uom_id": self.product.uom_po_id.id,
                            "price_unit": 12.5,
                        },
                    )
                ],
            }
        )
        po.button_confirm()
        intake = self.Intake.ingest_parseur_payload(
            {
                "document_type": "delivery_note",
                "supplier_vat": "ESA12345674",
                "po_number": po.name,
                "document_number": "ALB-89",
                "items": [{"sku": "WOOD-01", "qty": 4, "unit_price": 12.5}],
            }
        )
        intake.action_apply()
        self.assertEqual(intake.purchase_id, po)
        self.assertEqual(intake.picking_id.state, "done")

    def test_duplicate_parseur_id_is_ignored(self):
        payload = {
            "DocumentID": "abc123",
            "document_type": "delivery_note",
            "supplier_vat": "ESA12345674",
            "document_number": "ALB-90",
            "items": [{"sku": "WOOD-01", "qty": 1}],
        }
        first = self.Intake.ingest_parseur_payload(payload)
        second = self.Intake.ingest_parseur_payload(payload)
        self.assertEqual(first, second)
