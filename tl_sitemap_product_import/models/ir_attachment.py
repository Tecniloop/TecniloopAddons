import hashlib

from odoo import fields, models


class IrAttachment(models.Model):
    _inherit = "ir.attachment"

    sitemap_source_url = fields.Char(
        string="URL de origen sitemap", index=True, copy=False,
        help="URL pública desde la que el importador descargó este documento.",
    )
    sitemap_sha256 = fields.Char(
        string="SHA-256 sitemap", index=True, copy=False,
        help="Huella del contenido usada para evitar documentos duplicados.",
    )
    sitemap_document_type = fields.Selection([
        ("manual", "Manual / instrucciones"),
        ("technical", "Ficha técnica"),
        ("spare_parts", "Repuestos / despiece"),
        ("certificate", "Certificado"),
        ("catalog", "Catálogo / folleto"),
        ("warranty", "Garantía"),
        ("software", "Software / firmware"),
        ("other", "Otro"),
    ], string="Tipo de documento sitemap", copy=False)
    sitemap_imported = fields.Boolean(
        string="Importado por sitemap", default=False, index=True, copy=False)

    @staticmethod
    def sitemap_content_sha256(content):
        return hashlib.sha256(content or b"").hexdigest()
