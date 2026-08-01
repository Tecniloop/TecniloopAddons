# Copyright Tecniloop
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
from odoo import fields, models


class ProductTemplate(models.Model):
    _inherit = "product.template"

    piko_source_id = fields.Many2one("tl.piko.source", "Fuente de scraping", copy=False)
    piko_external_id = fields.Char("ID externo", copy=False, index=True)
    piko_url = fields.Char("URL de origen", copy=False)
    piko_last_sync = fields.Datetime("Última sincronización", copy=False, readonly=True)
    piko_price_locked = fields.Boolean(
        "Precio fijado manualmente",
        help="Si está marcado, el importador nunca sobrescribe el precio de venta.",
    )
    piko_no_overwrite = fields.Boolean(
        "No sobrescribir",
        help="Excluye este producto de cualquier actualización automática.",
    )

    def action_open_piko_url(self):
        self.ensure_one()
        return {"type": "ir.actions.act_url", "url": self.piko_url, "target": "new"}
