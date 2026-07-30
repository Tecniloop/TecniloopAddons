# Copyright 2026 Tecniloop
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    credit_advance_unpaid_warn = fields.Boolean(
        related="company_id.credit_advance_unpaid_warn", readonly=False
    )
    credit_advance_unpaid_threshold = fields.Monetary(
        related="company_id.credit_advance_unpaid_threshold", readonly=False
    )
