# Copyright 2026 Tecniloop
# License Other proprietary.

from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestVatAndExtraLine(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["ir.config_parameter"].sudo().set_param(
            "vendor_parseur_intake.validate_vat_format", "False"
        )
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.partner = cls.env["res.partner"].create(
            {
                "name": "VAT Vendor",
                "vat": "ESA12345674",
                "supplier_rank": 1,
            }
        )
        cls.product = cls.env["product.product"].create(
            {
                "name": "VAT board",
                "default_code": "VAT-01",
                "is_storable": True,
                "purchase_ok": True,
            }
        )

    def test_vat_with_spaces_and_dashes_matches_partner(self):
        intake = self.env["vendor.document.intake"].ingest_parseur_payload(
            {
                "document_type": "albaran",
                "supplier_vat": "ES A-12345674",
                "document_number": "ALB-VAT-1",
                "items": [{"sku": "VAT-01", "qty": 1}],
            }
        )
        self.assertEqual(intake.partner_id, self.partner)

    def test_extra_line_without_expense_account_raises(self):
        self.env["ir.config_parameter"].sudo().set_param(
            "vendor_parseur_intake.price_diff_mode", "extra_line"
        )
        self.product.property_account_expense_id = False
        if "property_account_expense_categ_id" in self.product.categ_id._fields:
            self.product.categ_id.property_account_expense_categ_id = False
        intake = self.env["vendor.document.intake"].create(
            {
                "document_type": "vendor_bill",
                "partner_id": self.partner.id,
                "state": "matched",
            }
        )
        line = self.env["vendor.document.intake.line"].create(
            {
                "intake_id": intake.id,
                "product_id": self.product.id,
                "qty_document": 1,
                "price_unit": 20.0,
                "price_reference": 10.0,
                "price_variance": 10.0,
                "price_exception": True,
                "price_decision": "accept_document",
            }
        )
        invoice = self.env["account.move"].create(
            {
                "move_type": "in_invoice",
                "partner_id": self.partner.id,
            }
        )
        with patch.object(
            type(self.product.product_tmpl_id),
            "get_product_accounts",
            return_value={"expense": self.env["account.account"]},
        ):
            with self.assertRaises(UserError):
                intake._apply_price_decision_on_invoice(invoice)
        self.assertFalse(
            invoice.invoice_line_ids.filtered(lambda l: not l.product_id and not l.account_id)
        )
        self.assertTrue(line.price_exception)
