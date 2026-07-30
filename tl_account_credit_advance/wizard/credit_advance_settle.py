# Copyright 2026 Tecniloop
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

from odoo import api, fields, models
from odoo.exceptions import UserError


class CreditAdvanceSettle(models.TransientModel):
    """Cancels the financial debt against the assigned receivables once the
    customers have effectively paid at maturity.

        (5208) Debt for discounted effects    nominal
                to (4311) Assigned receivables         nominal

    No bank account is involved: the money never came back to us, the bank
    simply stops having a claim on the funds it advanced. Both legs are
    reconciled so the effect and the debt disappear from the open items.
    """

    _name = "credit.advance.settle"
    _description = "Settle Matured Effects"

    order_id = fields.Many2one(
        comodel_name="account.payment.order", string="Remittance"
    )
    credit_advance_line_id = fields.Many2one(
        comodel_name="credit.advance.line",
        string="Credit Advance Line",
        required=True,
    )
    company_id = fields.Many2one(
        related="credit_advance_line_id.company_id", readonly=True
    )
    currency_id = fields.Many2one(
        related="credit_advance_line_id.currency_id", readonly=True
    )
    journal_id = fields.Many2one(
        comodel_name="account.journal",
        string="Journal",
        required=True,
        domain="[('company_id', '=', company_id)]",
    )
    date = fields.Date(required=True, default=fields.Date.context_today)
    payment_ids = fields.Many2many(
        comodel_name="account.payment",
        string="Effects",
        required=True,
        domain="[('credit_advance_line_id', '=', credit_advance_line_id), "
        "('credit_advance_state', 'in', ('assigned', 'advanced'))]",
    )
    total_amount = fields.Monetary(
        compute="_compute_total_amount", currency_field="currency_id"
    )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        payments = self.env["account.payment"].browse(
            self.env.context.get("default_payment_ids", [])
        )
        order = self.env["account.payment.order"].browse(res.get("order_id"))
        line = order.credit_advance_line_id or payments.credit_advance_line_id[:1]
        if line:
            res["credit_advance_line_id"] = line.id
            res.setdefault("journal_id", line.settlement_journal_id.id)
        if order and not payments:
            res["payment_ids"] = [
                (
                    6,
                    0,
                    order.payment_ids.filtered(
                        lambda p: p.credit_advance_state in ("assigned", "advanced")
                    ).ids,
                )
            ]
        return res

    @api.depends("payment_ids")
    def _compute_total_amount(self):
        for wizard in self:
            wizard.total_amount = sum(
                wizard.payment_ids.mapped("credit_advance_amount")
            )

    def action_confirm(self):
        """Settle now, through the same entry the scheduler would have written."""
        self.ensure_one()
        line = self.credit_advance_line_id
        payments = self.payment_ids
        payments._check_credit_advance_ready(self.env._("settled"))
        if payments.credit_advance_line_id != line:
            raise UserError(
                self.env._(
                    "All the selected effects must belong to the same credit "
                    "advance line."
                )
            )
        scheduled = payments.filtered(
            lambda p: p.credit_advance_settle_move_id.state == "draft"
        )
        if scheduled:
            raise UserError(
                self.env._(
                    "These effects already have a settlement entry waiting to "
                    "be posted: %(effects)s.\n\nPost that entry instead of "
                    "creating a second one.",
                    effects=", ".join(scheduled.mapped("display_name")),
                )
            )
        move_lines = []
        for payment in payments:
            move_lines += line._prepare_settlement_line_vals(payment)
        move = self.env["account.move"].create(
            {
                "journal_id": self.journal_id.id,
                "date": self.date,
                "ref": self.env._("Settlement of matured effects"),
                "company_id": self.company_id.id,
                "credit_advance_line_id": line.id,
                "credit_advance_move_type": "settlement",
                "line_ids": [(0, 0, vals) for vals in move_lines],
            }
        )
        # Posting the entry reconciles it and closes the effects, so that the
        # manual path and the scheduled one behave identically.
        move.action_post()
        return {
            "type": "ir.actions.act_window",
            "res_model": "account.move",
            "view_mode": "form",
            "res_id": move.id,
        }
