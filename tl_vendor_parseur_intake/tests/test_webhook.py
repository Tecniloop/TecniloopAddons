# Copyright 2026 Tecniloop
# License Other proprietary.

import json

from odoo.tests import tagged
from odoo.tests.common import HttpCase


@tagged("post_install", "-at_install")
class TestParseurWebhook(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["ir.config_parameter"].sudo().set_param(
            "vendor_parseur_intake.validate_vat_format", "False"
        )
        cls.env["ir.config_parameter"].sudo().set_param(
            "vendor_parseur_intake.webhook_token", "secret-token"
        )
        cls.env["res.partner"].create(
            {
                "name": "Hook Vendor",
                "vat": "ESD1234567H",
                "supplier_rank": 1,
            }
        )
        cls.env["product.product"].create(
            {
                "name": "Hook wood",
                "default_code": "HOOK-01",
                "is_storable": True,
                "purchase_ok": True,
            }
        )

    def _post(self, payload, token=None, headers=None):
        hdrs = {"Content-Type": "application/json"}
        if token:
            hdrs["X-Webhook-Token"] = token
        if headers:
            hdrs.update(headers)
        return self.url_open(
            "/parseur/vendor/intake",
            data=json.dumps(payload).encode(),
            headers=hdrs,
        )

    def test_webhook_rejects_invalid_token(self):
        response = self._post({"document_type": "albaran"}, token="wrong")
        self.assertEqual(response.status_code, 401)

    def test_webhook_creates_intake(self):
        response = self._post(
            {
                "DocumentID": "hook-1",
                "document_type": "albaran",
                "supplier_vat": "ESD1234567H",
                "document_number": "ALB-HOOK-1",
                "items": [{"sku": "HOOK-01", "qty": 1}],
            },
            token="secret-token",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data.get("ok"))
        self.assertTrue(data.get("intake_id"))
        intake = self.env["vendor.document.intake"].browse(data["intake_id"])
        self.assertEqual(intake.parseur_document_id, "hook-1")
        self.assertEqual(intake.currency_id, self.env.company.currency_id)

    def test_webhook_same_document_id_is_idempotent(self):
        payload = {
            "DocumentID": "hook-dup",
            "document_type": "albaran",
            "supplier_vat": "ESD1234567H",
            "document_number": "ALB-HOOK-DUP",
            "items": [{"sku": "HOOK-01", "qty": 1}],
        }
        first = self._post(payload, token="secret-token")
        second = self._post(payload, token="secret-token")
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.json()["intake_id"], second.json()["intake_id"])
        count = self.env["vendor.document.intake"].search_count(
            [("parseur_document_id", "=", "hook-dup")]
        )
        self.assertEqual(count, 1)
