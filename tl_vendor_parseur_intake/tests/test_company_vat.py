# Copyright 2026 Tecniloop
# License Other proprietary.

from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestCompanyVatRouting(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["ir.config_parameter"].sudo().set_param(
            "vendor_parseur_intake.validate_vat_format", "False"
        )
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.company = cls.env.company
        if not cls.company.vat:
            cls.company.vat = "ESA00000000"
        cls.env["res.partner"].create(
            {
                "name": "Co Vendor",
                "vat": "ESB0000000X",
                "supplier_rank": 1,
            }
        )
        cls.env["product.product"].create(
            {
                "name": "Co item",
                "default_code": "CO-01",
                "is_storable": True,
                "purchase_ok": True,
            }
        )

    def test_bill_routes_to_company_by_vat(self):
        intake = self.env["vendor.document.intake"].ingest_parseur_payload(
            {
                "document_type": "factura",
                "company_vat": self.company.vat,
                "supplier_vat": "ESB0000000X",
                "invoice_number": "F-CO-1",
                "items": [{"sku": "CO-01", "qty": 1, "unit_price": 1.0}],
            }
        )
        self.assertEqual(intake.company_id, self.company)

    def test_bill_unknown_company_vat_is_exception(self):
        extra = self.env["res.company"].search([("id", "!=", self.company.id)], limit=1)
        if not extra:
            extra = self.env["res.company"].create({"name": "Other Co", "vat": "ESB11111111"})
        intake = self.env["vendor.document.intake"].ingest_parseur_payload(
            {
                "document_type": "factura",
                "company_vat": "ESZ9999999Z",
                "supplier_vat": "ESB0000000X",
                "invoice_number": "F-CO-BAD",
                "items": [{"sku": "CO-01", "qty": 1, "unit_price": 1.0}],
            }
        )
        self.assertEqual(intake.state, "exception")
        self.assertTrue(intake.exception_reason)

    def _alt_company(self):
        usd = self.env.ref("base.USD", raise_if_not_found=False)
        gbp = self.env.ref("base.GBP", raise_if_not_found=False)
        alt = next(
            (cur for cur in (usd, gbp) if cur and cur != self.env.company.currency_id),
            False,
        )
        if not alt:
            self.skipTest("Need USD or GBP distinct from the current company currency")
        alt.active = True
        existing = self.env["res.company"].search([("vat", "=", "ESUSDCO1234")], limit=1)
        if existing:
            existing.currency_id = alt
            return existing, alt
        try:
            other = self.env["res.company"].create(
                {
                    "name": "Alt currency Co",
                    "vat": "ESUSDCO1234",
                    "currency_id": alt.id,
                }
            )
        except Exception as err:
            self.skipTest("Could not create a second company: %s" % err)
        return other, alt

    def test_currency_follows_resolved_company(self):
        other, alt = self._alt_company()
        intake = self.env["vendor.document.intake"].with_company(self.env.company).ingest_parseur_payload(
            {
                "document_type": "factura",
                "company_vat": other.vat,
                "supplier_vat": "ESB0000000X",
                "invoice_number": "F-CO-USD",
                "items": [{"sku": "CO-01", "qty": 1, "unit_price": 1.0}],
            }
        )
        self.assertEqual(intake.company_id, other)
        self.assertEqual(intake.currency_id, alt)

    def test_payload_currency_wins_over_company(self):
        other, alt = self._alt_company()
        gbp = self.env.ref("base.GBP", raise_if_not_found=False)
        usd = self.env.ref("base.USD", raise_if_not_found=False)
        explicit = gbp if gbp and gbp != alt else usd
        if not explicit or explicit == alt:
            self.skipTest("Need two distinct foreign currencies")
        explicit.active = True
        intake = self.env["vendor.document.intake"].with_company(self.env.company).ingest_parseur_payload(
            {
                "document_type": "factura",
                "company_vat": other.vat,
                "currency": explicit.name,
                "supplier_vat": "ESB0000000X",
                "invoice_number": "F-CO-EXPLICIT",
                "items": [{"sku": "CO-01", "qty": 1, "unit_price": 1.0}],
            }
        )
        self.assertEqual(intake.company_id, other)
        self.assertEqual(intake.currency_id, explicit)

    def test_unknown_payload_currency_falls_back_to_company(self):
        other, alt = self._alt_company()
        intake = self.env["vendor.document.intake"].with_company(self.env.company).ingest_parseur_payload(
            {
                "document_type": "factura",
                "company_vat": other.vat,
                "currency": "ZZZ",
                "supplier_vat": "ESB0000000X",
                "invoice_number": "F-CO-ZZZ",
                "items": [{"sku": "CO-01", "qty": 1, "unit_price": 1.0}],
            }
        )
        self.assertEqual(intake.currency_id, alt)

    def test_resolve_currency_without_record_uses_passed_company(self):
        other, alt = self._alt_company()
        Intake = self.env["vendor.document.intake"]
        currency = Intake._resolve_currency(False, company=other)
        self.assertEqual(currency, alt)
        fallback = Intake._resolve_currency(False)
        self.assertEqual(fallback, self.env.company.currency_id)
