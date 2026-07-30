# Copyright 2026 Tecniloop
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    credit_advance_unpaid_warn = fields.Boolean(
        string="Warn on Customers with Unpaid Effects",
        help="Show the financial risk wizard when posting an invoice for a "
        "customer that has effects charged back by the bank, even if their "
        "risk limits are not exceeded.",
    )
    credit_advance_unpaid_threshold = fields.Monetary(
        string="Unpaid Effects Threshold",
        currency_field="currency_id",
        help="Only warn when the charged-back effects of the customer exceed "
        "this amount. Leave at 0 to warn on any amount.",
    )
