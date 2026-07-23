# Copyright 2026 Tecniloop
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
from odoo import fields, models


class SuenlaceImportWizard(models.TransientModel):
    _inherit = "tl.suenlace.import.wizard"

    async_mode = fields.Boolean(
        string="Proceso asíncrono",
        default=True,
        help="Encola el parseo mediante OCA Queue Job.",
    )

    def _prepare_import_vals(self):
        vals = super()._prepare_import_vals()
        vals["async_mode"] = self.async_mode
        return vals
