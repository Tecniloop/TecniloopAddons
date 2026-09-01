# Copyright 2026 Tecniloop
# License Other proprietary.

from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestViesCheck(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.partner = cls.env["res.partner"].create(
            {
                "name": "VIES Vendor",
                "vat": "ESB12345674",
                "supplier_rank": 1,
            }
        )
        cls.intake = cls.env["vendor.document.intake"].create(
            {
                "document_type": "vendor_bill",
                "supplier_vat": "ESB12345674",
                "partner_id": cls.partner.id,
                "state": "identified",
            }
        )

    def _enable_vies(self, enabled=True):
        self.env["ir.config_parameter"].sudo().set_param(
            "vendor_parseur_intake.validate_vat_vies",
            "True" if enabled else "False",
        )

    def test_vies_disabled_does_not_call_backends(self):
        self._enable_vies(False)
        with patch(
            "odoo.addons.tl_vendor_parseur_intake.models.vat_utils.check_vies_soap"
        ) as soap, patch.object(
            type(self.partner), "_check_vies_iap", create=True
        ) as iap:
            self.intake._maybe_vies_check()
            soap.assert_not_called()
            iap.assert_not_called()

    def test_iap_valid_posts_acceptance(self):
        self._enable_vies(True)
        with patch.object(
            type(self.partner), "_check_vies_iap", create=True, return_value="valid"
        ), patch(
            "odoo.addons.tl_vendor_parseur_intake.models.vat_utils.check_vies_soap"
        ) as soap:
            self.intake._maybe_vies_check()
            soap.assert_not_called()
        bodies = " ".join(self.intake.message_ids.mapped("body"))
        self.assertIn("IAP", bodies)
        self.assertIn("accepted", bodies.lower())

    def test_iap_down_soap_false_raises(self):
        self._enable_vies(True)
        with patch.object(
            type(self.partner),
            "_check_vies_iap",
            create=True,
            side_effect=RuntimeError("iap down"),
        ), patch(
            "odoo.addons.tl_vendor_parseur_intake.models.vat_utils.check_vies_soap",
            return_value=False,
        ):
            with self.assertRaises(UserError) as err:
                self.intake._maybe_vies_check()
        self.assertIn("VIES rejected", str(err.exception))

    def test_soap_timeout_does_not_raise(self):
        self._enable_vies(True)
        with patch.object(
            type(self.partner),
            "_check_vies_iap",
            create=True,
            side_effect=RuntimeError("iap down"),
        ), patch(
            "odoo.addons.tl_vendor_parseur_intake.models.vat_utils.check_vies_soap",
            return_value=None,
        ):
            self.intake._maybe_vies_check()
        bodies = " ".join(self.intake.message_ids.mapped("body"))
        self.assertIn("could not be reached", bodies)
