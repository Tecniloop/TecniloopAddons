# Copyright 2026 Ecmr DeCA contributors
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import hashlib
import io
from unittest.mock import patch

try:
    from pypdf import PdfReader, PdfWriter
except ImportError:  # pragma: no cover - selected by the Odoo Python runtime
    from PyPDF2 import PdfReader, PdfWriter

from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged
from odoo.tests.common import new_test_user


@tagged("post_install", "-at_install")
class TestDeca(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["ir.config_parameter"].sudo().set_param(
            "l10n_es_deca.public_base_url", "https://deca.example.test"
        )
        cls.deca_user = new_test_user(
            cls.env,
            login="deca_test_user",
            groups="l10n_es_deca.group_deca_manager",
        )
        cls.shipper = cls.env["res.partner"].create(
            {
                "name": "Cargador Contractual SL",
                "vat": "ESB12345678",
                "street": "Calle Mayor 1",
                "city": "Madrid",
                "zip": "28001",
                "country_id": cls.env.ref("base.es").id,
            }
        )
        cls.carrier = cls.env["res.partner"].create(
            {"name": "Transportista Efectivo SL", "vat": "ESB87654321"}
        )
        cls.picking_type = cls.env["stock.picking.type"].search(
            [
                ("code", "=", "outgoing"),
                ("warehouse_id.company_id", "=", cls.env.company.id),
            ],
            limit=1,
        )

    def _new_picking(self):
        return self.env["stock.picking"].create(
            {
                "picking_type_id": self.picking_type.id,
                "location_id": self.picking_type.default_location_src_id.id,
                "location_dest_id": self.picking_type.default_location_dest_id.id,
                "partner_id": self.shipper.id,
            }
        )

    def _new_document(self):
        picking = self._new_picking()
        return (
            self.env["l10n.es.deca.document"]
            .with_user(self.deca_user)
            .create(
                {
                    "picking_id": picking.id,
                    "contractual_shipper_id": self.shipper.id,
                    "contractual_shipper_name": self.shipper.name,
                    "contractual_shipper_vat": self.shipper.vat,
                    "contractual_shipper_address": "Calle Mayor 1\n28001 Madrid",
                    "effective_carrier_id": self.carrier.id,
                    "effective_carrier_name": self.carrier.name,
                    "effective_carrier_vat": self.carrier.vat,
                    "origin": "Madrid",
                    "destination": "Valencia",
                    "goods_nature": "Mercancía general paletizada",
                    "goods_weight": 1200.0,
                    "weight_uom": "kg",
                    "tractor_plate": "1234ABC",
                    "driver_name": "Conductor Prueba",
                }
            )
        )

    @staticmethod
    def _minimal_pdf():
        writer = PdfWriter()
        writer.add_blank_page(width=595, height=842)
        output = io.BytesIO()
        writer.write(output)
        return output.getvalue()

    def _issue(self, document):
        report_model = self.env["ir.actions.report"].__class__
        with patch.object(
            report_model,
            "_render_qweb_pdf",
            autospec=True,
            return_value=(self._minimal_pdf(), "pdf"),
        ):
            document.action_issue()
        return document.current_version_id

    def test_issue_seals_pdf_with_url_hash_and_metadata(self):
        document = self._new_document()
        version = self._issue(document)
        self.assertEqual(document.state, "issued")
        self.assertTrue(
            version.public_url.startswith("https://deca.example.test/deca/pdf/")
        )
        self.assertTrue(version.qr_code)
        self.assertLessEqual(version.pdf_size, 5 * 1024 * 1024)
        self.assertEqual(
            hashlib.sha256(version.get_pdf_bytes()).hexdigest(), version.pdf_sha256
        )
        metadata = PdfReader(io.BytesIO(version.get_pdf_bytes())).metadata
        self.assertTrue(metadata.get("/CreationDate"))
        self.assertTrue(metadata.get("/ModDate"))

    def test_real_qweb_report_is_sealed_as_pdf(self):
        """Exercise the installed Odoo 19 QWeb/wkhtmltopdf stack without mocking."""
        document = self._new_document()
        document.action_issue()
        self.assertTrue(
            document.current_version_id.get_pdf_bytes().startswith(b"%PDF")
        )

    def test_missing_weight_or_alternative_is_rejected(self):
        document = self._new_document()
        document.goods_weight = 0
        with self.assertRaises(ValidationError):
            document.action_issue()

    def test_unissued_cancelled_document_can_be_reopened(self):
        document = self._new_document()
        document.action_cancel()
        self.assertEqual(document.state, "cancelled")
        document.action_reset_to_draft()
        self.assertEqual(document.state, "draft")

    def test_sealed_document_and_version_are_immutable(self):
        document = self._new_document()
        version = self._issue(document)
        with self.assertRaises(UserError):
            document.write({"destination": "Bilbao"})
        with self.assertRaises(UserError):
            version.with_user(self.deca_user).write({"change_reason": "tamper"})
        with self.assertRaises(UserError):
            version.with_user(self.deca_user).unlink()

    def test_forged_private_context_does_not_bypass_workflow(self):
        document = self._new_document()
        with self.assertRaises(UserError):
            document.with_context(_deca_internal_write=True).write(
                {"state": "issued"}
            )
        with self.assertRaises(UserError):
            self.env["l10n.es.deca.version"].with_user(self.deca_user).with_context(
                _deca_create_version=True
            ).create({})

    def test_driver_delivery_is_required_before_start(self):
        document = self._new_document()
        version = self._issue(document)
        with self.assertRaises(UserError):
            document.action_start_transport()
        self.env["l10n.es.deca.delivery.log"].with_user(self.deca_user).create(
            {
                "version_id": version.id,
                "method": "mobile",
                "recipient_name": "Conductor Prueba",
            }
        )
        document.action_start_transport()
        self.assertEqual(document.state, "in_transit")
        self.assertTrue(document.actual_start_at)

    def test_revision_preserves_previous_pdf_and_changes_url(self):
        document = self._new_document()
        first = self._issue(document)
        self.env["l10n.es.deca.delivery.log"].with_user(self.deca_user).create(
            {
                "version_id": first.id,
                "method": "mobile",
                "recipient_name": "Conductor Prueba",
            }
        )
        document.action_start_transport()
        old_pdf = first.get_pdf_bytes()
        values = {}
        for name in document._get_legal_fields():
            value = document[name]
            values[name] = (
                value.id if document._fields[name].type == "many2one" else value
            )
        values["destination"] = "Barcelona"
        report_model = self.env["ir.actions.report"].__class__
        with patch.object(
            report_model,
            "_render_qweb_pdf",
            autospec=True,
            return_value=(self._minimal_pdf(), "pdf"),
        ):
            second = document._apply_revision(
                values, "Cambio de destino solicitado", expected_version=first
            )
        self.assertEqual(second.version_number, 2)
        self.assertEqual(second.previous_version_id, first)
        self.assertNotEqual(second.public_url, first.public_url)
        self.assertEqual(first.get_pdf_bytes(), old_pdf)
        self.assertEqual(document.destination, "Barcelona")
        self.assertEqual(document.state, "in_transit")
        with self.assertRaises(UserError):
            document.action_complete_transport()
        self.env["l10n.es.deca.delivery.log"].with_user(self.deca_user).create(
            {
                "version_id": second.id,
                "method": "mobile",
                "recipient_name": "Conductor Prueba",
            }
        )
        document.action_complete_transport()
        self.assertEqual(document.state, "done")

    def test_contractual_purpose_fails_closed_without_signing_addon(self):
        document = self._new_document()
        document.purpose = "contractual"
        with self.assertRaisesRegex(ValidationError, "signature addon"):
            self._issue(document)
