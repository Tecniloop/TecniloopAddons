# Copyright 2026 Tecniloop
# License Other proprietary.

from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestApplyBatch(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["ir.config_parameter"].sudo().set_param(
            "vendor_parseur_intake.validate_vat_format", "False"
        )
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.partner = cls.env["res.partner"].create(
            {
                "name": "Batch Vendor",
                "vat": "ESE1234567B",
                "supplier_rank": 1,
            }
        )
        cls.product = cls.env["product.product"].create(
            {
                "name": "Batch plank",
                "default_code": "BATCH-01",
                "is_storable": True,
                "purchase_ok": True,
            }
        )
        cls.Intake = cls.env["vendor.document.intake"]

    def test_batch_apply_keeps_successful_document(self):
        good = self.Intake.ingest_parseur_payload(
            {
                "document_type": "albaran",
                "supplier_vat": "ESE1234567B",
                "document_number": "ALB-BATCH-OK",
                "items": [{"sku": "BATCH-01", "qty": 2, "unit_price": 3.0}],
            }
        )
        bad = self.Intake.create(
            {
                "document_type": "delivery_note",
                "state": "identified",
                "document_number": "ALB-BATCH-BAD",
            }
        )
        (good | bad).action_apply()
        self.assertEqual(good.state, "applied")
        self.assertTrue(good.purchase_id)
        self.assertEqual(bad.state, "exception")
        self.assertTrue(bad.exception_reason)
