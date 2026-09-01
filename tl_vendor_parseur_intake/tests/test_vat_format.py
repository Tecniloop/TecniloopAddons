# Copyright 2026 Tecniloop
# License Other proprietary.

from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestVatFormatValidation(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["ir.config_parameter"].sudo().set_param(
            "vendor_parseur_intake.validate_vat_format", "True"
        )
        cls.company = cls.env.company
        cls.company.vat = "ES00000000T"
        cls.env["res.partner"].create(
            {
                "name": "Format Vendor",
                "vat": "ES00000000T",
                "supplier_rank": 1,
            }
        )
        cls.env["product.product"].create(
            {
                "name": "Format item",
                "default_code": "FMT-01",
                "is_storable": True,
                "purchase_ok": True,
            }
        )

    def test_invalid_supplier_vat_sets_exception(self):
        intake = self.env["vendor.document.intake"].ingest_parseur_payload(
            {
                "document_type": "albaran",
                "supplier_vat": "ESB1",
                "document_number": "ALB-VAT-BAD",
                "items": [{"sku": "FMT-01", "qty": 1}],
            }
        )
        self.assertEqual(intake.state, "exception")
        self.assertIn("VAT format", intake.exception_reason or "")

    def test_same_company_and_supplier_vat_sets_exception(self):
        intake = self.env["vendor.document.intake"].ingest_parseur_payload(
            {
                "document_type": "factura",
                "company_vat": "ES00000000T",
                "supplier_vat": "ES00000000T",
                "invoice_number": "F-VAT-SAME",
                "items": [{"sku": "FMT-01", "qty": 1, "unit_price": 1}],
            }
        )
        self.assertEqual(intake.state, "exception")
        self.assertIn("same", (intake.exception_reason or "").lower())
