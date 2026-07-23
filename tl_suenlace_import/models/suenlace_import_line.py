# Copyright 2026 Tecniloop
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
from odoo import fields, models


class SuenlaceImportLine(models.Model):
    """Registro individual parseado del fichero (trazabilidad y reproceso)."""

    _name = "tl.suenlace.import.line"
    _description = "Registro SUENLACE parseado"
    _order = "sequence"

    import_id = fields.Many2one(
        "tl.suenlace.import",
        string="Importación",
        required=True,
        ondelete="cascade",
        index=True,
    )
    sequence = fields.Integer(string="Nº registro")
    record_type = fields.Char(string="Tipo", index=True)
    payload = fields.Text(string="Contenido parseado")
    unsupported = fields.Boolean(string="No soportado")
