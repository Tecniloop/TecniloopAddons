# Copyright 2026 Ecmr DeCA contributors
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import base64
import hashlib
import io
from datetime import timedelta

try:
    from pypdf import PdfWriter
except ImportError:  # pragma: no cover - selected by the Odoo Python runtime
    from PyPDF2 import PdfWriter

from odoo import fields
from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install")
class TestDecaPublicDownload(HttpCase):
    @staticmethod
    def _minimal_pdf():
        writer = PdfWriter()
        writer.add_blank_page(width=595, height=842)
        output = io.BytesIO()
        writer.write(output)
        return output.getvalue()

    def _sealed_public_version(self):
        document = self.env["l10n.es.deca.document"].sudo().create({})
        now = fields.Datetime.now()
        token = "A" * 43
        version = (
            self.env["l10n.es.deca.version"]
            .sudo()
            .with_context(_deca_create_version=True)
            .create(
                {
                    "document_id": document.id,
                    "version_number": 1,
                    "data_snapshot": {},
                    "created_at": now,
                    "modified_at": now,
                    "public_until": now + timedelta(days=1),
                    "access_token": token,
                    "public_url": f"https://deca.example.test/deca/pdf/{token}",
                    "pdf_filename": "DeCA-http-test.pdf",
                }
            )
        )
        pdf = self._minimal_pdf()
        pdf_hash = hashlib.sha256(pdf).hexdigest()
        version.sudo().with_context(_deca_seal_version=True).write(
            {
                "pdf_data": base64.b64encode(pdf),
                "pdf_size": len(pdf),
                "pdf_sha256": pdf_hash,
                "chain_hash": hashlib.sha256(f":{pdf_hash}".encode()).hexdigest(),
            }
        )
        document.sudo().with_context(_deca_internal_write=True).write(
            {"state": "issued", "current_version_id": version.id}
        )
        return version, pdf

    def test_qr_url_downloads_exact_pdf_without_authentication(self):
        version, expected_pdf = self._sealed_public_version()
        response = self.url_open(f"/deca/pdf/{version.access_token}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Content-Type"], "application/pdf")
        self.assertIn("attachment", response.headers["Content-Disposition"])
        self.assertEqual(response.content, expected_pdf)

    def test_malformed_token_is_not_found(self):
        response = self.url_open("/deca/pdf/not-a-valid-token")
        self.assertEqual(response.status_code, 404)
