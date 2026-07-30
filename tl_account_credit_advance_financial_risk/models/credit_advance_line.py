# Copyright 2026 Tecniloop
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

from odoo import api, fields, models


class CreditAdvanceLine(models.Model):
    _inherit = "credit.advance.line"

    with_recourse = fields.Boolean(
        string="With Recourse",
        default=True,
        help="The bank can charge the effects back to us if the customer does "
        "not pay, which is the usual arrangement in a discount line. When "
        "enabled, the assigned receivables keep counting in the risk of the "
        "customer. Disable it only for a true non-recourse facility, where the "
        "default risk is transferred to the bank.",
    )
    partner_risk_check = fields.Selection(
        selection=[
            ("none", "No check"),
            ("warn", "Log a warning"),
            ("block", "Block the remittance"),
        ],
        default="none",
        required=True,
        string="Risk Check on Confirmation",
        help="What to do when a remittance financed through this line contains "
        "a customer whose financial risk is exceeded or who is over the "
        "concentration limit of the facility.",
    )
    # -- Concentration limit per debtor --
    partner_limit_amount = fields.Monetary(
        string="Limit per Customer",
        currency_field="currency_id",
        help="Maximum nominal amount a single customer may have assigned to "
        "this facility at any given time. Leave at 0 for no limit.",
    )
    partner_limit_percent = fields.Float(
        string="Limit per Customer (%)",
        digits=(16, 2),
        help="Same as above, expressed as a percentage of the facility limit. "
        "Banks usually cap the concentration of a single debtor this way. "
        "Leave at 0 for no limit.",
    )
    partner_limit_use_credit_limit = fields.Boolean(
        string="Cap by Customer Credit Limit",
        help="Also cap what a customer may have assigned to this facility by "
        "the credit limit set on their contact. This is what ties the facility "
        "control to the financial risk: a customer whose own credit limit is "
        "lower than the concentration limit of the facility is capped by their "
        "own limit.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        self.env.registry.clear_cache()
        return records

    def write(self, vals):
        res = super().write(vals)
        if {"account_assigned_id", "account_unpaid_id", "with_recourse"} & set(vals):
            self.env.registry.clear_cache()
        return res

    def unlink(self):
        res = super().unlink()
        self.env.registry.clear_cache()
        return res

    def _get_partner_limit(self, partner):
        """Effective concentration limit for a customer on this facility.

        The most restrictive of the configured caps wins. Returns 0.0 when
        nothing is configured, meaning no limit at all.
        """
        self.ensure_one()
        commercial = partner.commercial_partner_id
        candidates = []
        if self.partner_limit_amount:
            candidates.append(self.partner_limit_amount)
        if self.partner_limit_percent and self.limit_amount:
            candidates.append(self.limit_amount * self.partner_limit_percent / 100)
        if self.partner_limit_use_credit_limit and commercial.sudo().credit_limit:
            candidates.append(commercial.sudo().credit_limit)
        return min(candidates) if candidates else 0.0

    def _get_partner_drawn(self, partners=None):
        """Nominal assigned to this facility, per commercial partner."""
        self.ensure_one()
        domain = [
            ("credit_advance_line_id", "=", self.id),
            ("credit_advance_state", "in", ("assigned", "advanced")),
        ]
        if partners:
            domain.append(("partner_id", "in", partners.ids))
        groups = self.env["account.payment"]._read_group(
            domain, ["partner_id"], ["credit_advance_amount:sum"]
        )
        result = {}
        for partner, amount in groups:
            commercial = partner.commercial_partner_id
            result[commercial] = result.get(commercial, 0.0) + amount
        return result

    def action_view_partner_breakdown(self):
        """Assigned amount per customer on this facility."""
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "tl_account_credit_advance_financial_risk.credit_advance_risk_pivot_action"
        )
        action["domain"] = [("credit_advance_line_id", "=", self.id)]
        action["context"] = {
            "search_default_credit_advance_live": 1,
            "search_default_group_partner": 1,
        }
        return action
