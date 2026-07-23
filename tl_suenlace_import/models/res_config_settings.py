# Copyright 2026 Tecniloop
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    suenlace_associate_partners = fields.Boolean(
        related="company_id.suenlace_associate_partners",
        readonly=False,
    )
    suenlace_associate_taxes = fields.Boolean(
        related="company_id.suenlace_associate_taxes",
        readonly=False,
    )
