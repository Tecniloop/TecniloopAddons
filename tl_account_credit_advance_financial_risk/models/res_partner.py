# Copyright 2026 Tecniloop
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

from odoo import api, fields, models, tools
from odoo.fields import Domain


class ResPartner(models.Model):
    _inherit = "res.partner"

    risk_credit_advance_include = fields.Boolean(
        string="Include Advanced Effects",
        help="Include the receivables assigned to a bank under a credit advance "
        "line in the total risk of the customer. With a recourse facility the "
        "customer risk does not disappear when the bank advances the money: if "
        "the customer does not pay, the bank charges the effect back.",
    )
    risk_credit_advance_limit = fields.Monetary(
        string="Limit Advanced Effects",
        currency_field="risk_currency_id",
        help="Set 0 if it is not locked.",
    )
    risk_credit_advance = fields.Monetary(
        compute="_compute_risk_account_amount",
        store=True,
        string="Advanced Effects",
        currency_field="risk_currency_id",
        help="Total amount of the receivables assigned to a bank and pending of "
        "maturity.",
    )
    risk_credit_advance_unpaid_include = fields.Boolean(
        string="Include Unpaid Effects",
        help="Include the effects charged back by the bank in the total risk of "
        "the customer.",
    )
    risk_credit_advance_unpaid_limit = fields.Monetary(
        string="Limit Unpaid Effects",
        currency_field="risk_currency_id",
        help="Set 0 if it is not locked.",
    )
    risk_credit_advance_unpaid = fields.Monetary(
        compute="_compute_risk_account_amount",
        store=True,
        string="Unpaid Effects",
        currency_field="risk_currency_id",
        help="Total amount of the effects returned by the bank and still not "
        "recovered from the customer.",
    )

    @api.model
    @tools.ormcache()
    def _credit_advance_risk_accounts(self):
        """Map every credit advance account to the risk bucket it feeds.

        A value of ``False`` means the amount is removed from the risk: it is a
        non-recourse facility, so the bank, and not us, bears the default.
        """
        mapping = {}
        for line in self.env["credit.advance.line"].sudo().with_context(
            active_test=False
        ).search([]):
            mapping[line.account_assigned_id.id] = (
                "risk_credit_advance" if line.with_recourse else False
            )
            mapping.setdefault(
                line.account_unpaid_id.id, "risk_credit_advance_unpaid"
            )
        return mapping

    @api.depends(
        "move_line_ids.amount_residual",
        "move_line_ids.date_maturity",
        "company_id.invoice_unpaid_margin",
    )
    def _compute_risk_account_amount(self):
        self.update({"risk_credit_advance": 0.0, "risk_credit_advance_unpaid": 0.0})
        return super()._compute_risk_account_amount()

    def _prepare_risk_account_vals(self, groups):
        """Move the credit advance amounts out of the generic account bucket.

        ``account_financial_risk`` already counts any receivable account other
        than the customer one, so without this the assigned and the unpaid
        effects would be hidden inside ``risk_account_amount`` with no way of
        setting a specific limit for them. Amounts are classified by account and
        not by maturity: an effect whose due date has passed but has not been
        settled or charged back yet is still an advanced effect.
        """
        vals = super()._prepare_risk_account_vals(groups)
        mapping = self._credit_advance_risk_accounts()
        if not mapping:
            return vals
        vals.setdefault("risk_credit_advance", 0.0)
        vals.setdefault("risk_credit_advance_unpaid", 0.0)
        for key, source_field in (
            ("open", "risk_account_amount"),
            ("unpaid", "risk_account_amount_unpaid"),
        ):
            for (
                partner,
                account,
                currency,
                amount_residual,
                amount_residual_currency,
            ) in groups[key]["read_group"]:
                if partner.id not in self.ids or account.id not in mapping:
                    continue
                amount = self._get_amount_in_risk_currency(
                    currency, amount_residual_currency, amount_residual, account
                )
                vals[source_field] -= amount
                target_field = mapping[account.id]
                if target_field:
                    vals[target_field] += amount
        return vals

    def _get_field_risk_model_domain(self, field_name):
        """Domain behind the drill-down button of the new risk buckets."""
        if field_name not in ("risk_credit_advance", "risk_credit_advance_unpaid"):
            return super()._get_field_risk_model_domain(field_name)
        mapping = self._credit_advance_risk_accounts()
        account_ids = [
            account_id
            for account_id, target in mapping.items()
            if target == field_name
        ]
        domain = (
            self._get_risk_company_domain()
            & Domain(
                [
                    ("reconciled", "=", False),
                    ("parent_state", "=", "posted"),
                    ("account_id", "in", account_ids),
                ]
            )
            & Domain("partner_id", "in", self.ids)
        )
        return "account.move.line", domain

    def action_view_credit_advance_risk(self):
        """Open the breakdown of the customer risk per credit advance line."""
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "tl_account_credit_advance_financial_risk."
            "credit_advance_risk_pivot_action"
        )
        partners = self.commercial_partner_id | self.commercial_partner_id.child_ids
        action["domain"] = [
            ("credit_advance_line_id", "!=", False),
            ("partner_id", "in", partners.ids),
        ]
        action["context"] = {
            "search_default_group_line": 1,
            "search_default_group_state": 1,
        }
        return action

    @api.model
    def _risk_field_list(self):
        res = super()._risk_field_list()
        res.extend(
            [
                (
                    "risk_credit_advance",
                    "risk_credit_advance_limit",
                    "risk_credit_advance_include",
                ),
                (
                    "risk_credit_advance_unpaid",
                    "risk_credit_advance_unpaid_limit",
                    "risk_credit_advance_unpaid_include",
                ),
            ]
        )
        return res

    def _get_financial_risk_lines(self):
        res = super()._get_financial_risk_lines()
        res.extend(
            [
                (
                    self.risk_credit_advance_include,
                    self.risk_credit_advance,
                    self._fields["risk_credit_advance"].string,
                ),
                (
                    self.risk_credit_advance_unpaid_include,
                    self.risk_credit_advance_unpaid,
                    self._fields["risk_credit_advance_unpaid"].string,
                ),
            ]
        )
        return res
