# Copyright 2026 Ecmr DeCA contributors
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import io
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from pyhanko.pdf_utils.reader import PdfFileReader

try:
    from pypdf import PdfWriter
except ImportError:  # pragma: no cover - selected by the Odoo Python runtime
    from PyPDF2 import PdfWriter

from odoo import Command
from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged
from odoo.tests.common import new_test_user


@tagged("post_install", "-at_install")
class TestDecaAdes(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["ir.config_parameter"].sudo().set_param(
            "l10n_es_deca.public_base_url", "https://deca.example.test"
        )
        cls.company = cls.env.company
        cls.company.deca_ades_profile = "pades_b_b"
        cls.user = new_test_user(
            cls.env,
            login="deca_ades_test_user",
            groups="l10n_es_deca_ades.group_deca_ades_signer",
        )
        cls.carrier = cls.env["res.partner"].create(
            {
                "name": "Transportista Efectivo SL",
                "vat": "ESB87654321",
                "is_company": True,
            }
        )
        cls.carrier_company = cls.env["res.company"].create(
            {"name": "Transportista Efectivo SL", "partner_id": cls.carrier.id}
        )
        cls.user.write({"company_ids": [Command.link(cls.carrier_company.id)]})
        cls.picking_type = cls.env["stock.picking.type"].search(
            [
                ("code", "=", "outgoing"),
                ("warehouse_id.company_id", "=", cls.company.id),
            ],
            limit=1,
        )
        cls._certificate_directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls._certificate_directory.cleanup)
        cls.public_crt, cls.private_key = cls._create_test_certificate(
            Path(cls._certificate_directory.name), "shipper"
        )
        cls.carrier_public_crt, cls.carrier_private_key = (
            cls._create_test_certificate(
                Path(cls._certificate_directory.name), "carrier"
            )
        )

    @classmethod
    def _create_test_certificate(cls, directory, stem):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = issuer = x509.Name(
            [x509.NameAttribute(NameOID.COMMON_NAME, f"DeCA test signer {stem}")]
        )
        now = datetime.now(timezone.utc)
        certificate = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(days=1))
            .not_valid_after(now + timedelta(days=30))
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), True)
            .sign(key, hashes.SHA256())
        )
        private_key = directory / f"{stem}-private.pem"
        public_crt = directory / f"{stem}-public.pem"
        private_key.write_bytes(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
        public_crt.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
        return str(public_crt), str(private_key)

    @staticmethod
    def _minimal_pdf():
        writer = PdfWriter()
        writer.add_blank_page(width=595, height=842)
        output = io.BytesIO()
        writer.write(output)
        return output.getvalue()

    def _new_document(self):
        picking = self.env["stock.picking"].create(
            {
                "picking_type_id": self.picking_type.id,
                "location_id": self.picking_type.default_location_src_id.id,
                "location_dest_id": self.picking_type.default_location_dest_id.id,
            }
        )
        shipper = self.company.partner_id
        return (
            self.env["l10n.es.deca.document"]
            .with_user(self.user)
            .create(
                {
                    "purpose": "contractual",
                    "signature_party_policy": "shipper",
                    "shipper_signing_company_id": self.company.id,
                    "picking_id": picking.id,
                    "contractual_shipper_id": shipper.id,
                    "contractual_shipper_name": shipper.name,
                    "contractual_shipper_vat": shipper.vat or "ESA00000000",
                    "contractual_shipper_address": "Madrid",
                    "effective_carrier_id": self.carrier.id,
                    "effective_carrier_name": self.carrier.name,
                    "effective_carrier_vat": self.carrier.vat,
                    "origin": "Madrid",
                    "destination": "Valencia",
                    "goods_nature": "Mercancía general",
                    "goods_weight": 1000.0,
                    "tractor_plate": "1234ABC",
                }
            )
        )

    def test_contractual_issue_embeds_and_audits_pades(self):
        document = self._new_document()
        certificate_model = self.env["l10n.es.aeat.certificate"].__class__
        report_model = self.env["ir.actions.report"].__class__
        with (
            patch.object(
                certificate_model,
                "get_certificates",
                autospec=True,
                return_value=(self.public_crt, self.private_key),
            ),
            patch.object(
                report_model,
                "_render_qweb_pdf",
                autospec=True,
                return_value=(self._minimal_pdf(), "pdf"),
            ),
        ):
            document.action_issue()
        version = document.current_version_id
        reader = PdfFileReader(io.BytesIO(version.get_pdf_bytes()))
        self.assertEqual(len(reader.embedded_signatures), 1)
        self.assertEqual(version.signature_status, "complete")
        self.assertEqual(version.signature_count, 1)
        self.assertEqual(version.signature_profile, "PAdES B-B")
        self.assertEqual(version.signature_evidence["signatures"][0]["role"], "shipper")

    def test_signing_company_must_match_contractual_party(self):
        document = self._new_document()
        document.contractual_shipper_id = self.carrier
        with self.assertRaisesRegex(ValidationError, "does not match"):
            document.action_issue()

    def test_company_policy_defaults_new_contractual_draft(self):
        self.company.write(
            {
                "deca_default_purpose": "contractual",
                "deca_default_signature_party_policy": "both",
                "deca_default_shipper_signing_company_id": self.company.id,
                "deca_default_carrier_signing_company_id": self.carrier_company.id,
            }
        )
        document = (
            self.env["l10n.es.deca.document"]
            .with_user(self.user)
            .create({"company_id": self.company.id})
        )
        self.assertEqual(document.purpose, "contractual")
        self.assertEqual(document.signature_party_policy, "both")
        self.assertEqual(document.shipper_signing_company_id, self.company)
        self.assertEqual(
            document.carrier_signing_company_id, self.carrier_company
        )

    def test_company_policy_is_visible_in_new_form_defaults(self):
        self.company.write(
            {
                "deca_default_purpose": "contractual",
                "deca_default_signature_party_policy": "shipper",
                "deca_default_shipper_signing_company_id": self.company.id,
            }
        )
        field_names = [
            "company_id",
            "purpose",
            "signature_party_policy",
            "shipper_signing_company_id",
        ]
        values = (
            self.env["l10n.es.deca.document"]
            .with_user(self.user)
            .with_context(default_company_id=self.company.id)
            .default_get(field_names)
        )
        self.assertEqual(values["purpose"], "contractual")
        self.assertEqual(values["signature_party_policy"], "shipper")
        self.assertEqual(
            values["shipper_signing_company_id"], self.company.id
        )

    def test_company_policy_change_does_not_rewrite_existing_draft(self):
        document = (
            self.env["l10n.es.deca.document"]
            .with_user(self.user)
            .create(
                {
                    "company_id": self.company.id,
                    "purpose": "administrative",
                }
            )
        )
        self.company.deca_default_purpose = "contractual"
        self.assertEqual(document.purpose, "administrative")

    def test_explicit_draft_values_override_company_policy(self):
        self.company.write(
            {
                "deca_default_purpose": "contractual",
                "deca_default_signature_party_policy": "both",
            }
        )
        document = (
            self.env["l10n.es.deca.document"]
            .with_user(self.user)
            .create(
                {
                    "company_id": self.company.id,
                    "purpose": "administrative",
                    "signature_party_policy": "carrier",
                }
            )
        )
        self.assertEqual(document.purpose, "administrative")
        self.assertEqual(document.signature_party_policy, "carrier")

    def test_both_contractual_parties_are_signed_in_order(self):
        document = self._new_document()
        document.write(
            {
                "signature_party_policy": "both",
                "carrier_signing_company_id": self.carrier_company.id,
            }
        )
        certificate_model = self.env["l10n.es.aeat.certificate"].__class__
        report_model = self.env["ir.actions.report"].__class__

        def certificate_paths(_records, company=False):
            if company.id == self.carrier_company.id:
                return self.carrier_public_crt, self.carrier_private_key
            return self.public_crt, self.private_key

        with (
            patch.object(
                certificate_model,
                "get_certificates",
                autospec=True,
                side_effect=certificate_paths,
            ),
            patch.object(
                report_model,
                "_render_qweb_pdf",
                autospec=True,
                return_value=(self._minimal_pdf(), "pdf"),
            ),
        ):
            document.action_issue()
        version = document.current_version_id
        reader = PdfFileReader(io.BytesIO(version.get_pdf_bytes()))
        self.assertEqual(
            [signature.field_name for signature in reader.embedded_signatures],
            ["DeCA_shipper_1", "DeCA_carrier_1"],
        )
        self.assertEqual(version.signature_count, 2)
