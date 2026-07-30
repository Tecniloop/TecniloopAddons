# Copyright 2026 Tecniloop
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

from odoo import api, fields, models
from odoo.exceptions import UserError


class CreditAdvanceUnpaid(models.TransientModel):
    """Books the charge-back of an effect the customer did not pay.

        (5208) Debt for discounted effects    nominal
        (626)  Charge-back expenses           fees
                to (572) Bank                          nominal + fees

        (4315) Unpaid effects                 nominal
                to (4311) Assigned receivables         nominal

    The first entry cancels the debt with the bank and reflects that the bank
    takes the money back from our account. The second one returns the risk to
    the customer: the claim is alive again, either on the unpaid effects account
    or directly on the ordinary customer account.
    """

    _name = "credit.advance.unpaid"
    _description = "Register Charge-back"

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
    payment_ids = fields.Many2many(
        comodel_name="account.payment",
        string="Effects",
        required=True,
        domain="[('credit_advance_line_id', '=', credit_advance_line_id), "
        "('credit_advance_state', 'in', ('assigned', 'advanced'))]",
    )
    date = fields.Date(required=True, default=fields.Date.context_today)
    journal_id = fields.Many2one(
        comodel_name="account.journal",
        string="Bank Journal",
        required=True,
        domain="[('type', 'in', ('bank', 'general')), ('company_id', '=', company_id)]",
    )
    expense_amount = fields.Monetary(
        string="Charge-back Fees",
        currency_field="currency_id",
        help="Fees invoiced by the bank for the returned effects. They are "
        "debited to the expense account and taken from the bank account "
        "together with the nominal amount.",
    )
    expense_account_id = fields.Many2one(
        comodel_name="account.account", string="Expense Account"
    )
    claim_target = fields.Selection(
        selection=[
            ("unpaid", "Unpaid effects account"),
            ("receivable", "Ordinary customer account"),
        ],
        default="unpaid",
        required=True,
        string="Claim the Debt On",
        help="Where the debt goes back to. Using the unpaid effects account "
        "(PGC 4315) keeps the returned effects clearly separated in the customer "
        "ledger, which is usually what you want for follow-up and provisioning.",
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
        line = payments.credit_advance_line_id[:1]
        if line:
            res["credit_advance_line_id"] = line.id
            res.setdefault("journal_id", line.journal_id.id)
            res.setdefault(
                "expense_account_id",
                (
                    line.account_unpaid_expense_id or line.account_commission_id
                ).id,
            )
        return res

    @api.depends("payment_ids")
    def _compute_total_amount(self):
        for wizard in self:
            wizard.total_amount = sum(
                wizard.payment_ids.mapped("credit_advance_amount")
            )

    def _get_claim_account(self, payment):
        self.ensure_one()
        if self.claim_target == "unpaid":
            return self.credit_advance_line_id.account_unpaid_id
        account = payment.destination_account_id
        if not account:
            account = payment.partner_id.with_company(
                self.company_id
            ).property_account_receivable_id
        return account

    def action_confirm(self):
        self.ensure_one()
        line = self.credit_advance_line_id
        payments = self.payment_ids
        payments._check_credit_advance_ready(self.env._("unpaid"))
        if self.expense_amount and not self.expense_account_id:
            raise UserError(
                self.env._("Set the expense account for the charge-back fees.")
            )
        nominal = sum(payments.mapped("credit_advance_amount"))
        move_lines = [
            {
                "name": self.env._("Charge-back of unpaid effects"),
                "account_id": line.account_debt_id.id,
                "debit": nominal,
                "credit": 0.0,
                "partner_id": line.partner_id.id,
            },
            {
                "name": self.env._("Charge-back of unpaid effects"),
                "account_id": line._get_outstanding_account().id,
                "debit": 0.0,
                "credit": nominal + self.expense_amount,
                "partner_id": line.partner_id.id,
            },
        ]
        if self.expense_amount:
            move_lines.append(
                {
                    "name": self.env._("Charge-back fees"),
                    "account_id": self.expense_account_id.id,
                    "debit": self.expense_amount,
                    "credit": 0.0,
                    "partner_id": line.partner_id.id,
                    "analytic_distribution": line.analytic_distribution,
                }
            )
        assigned_lines = self.env["account.move.line"]
        for payment in payments:
            amount = payment.credit_advance_amount
            label = self.env._("Unpaid %s", payment.partner_id.name)
            move_lines.append(
                {
                    "name": label,
                    "account_id": self._get_claim_account(payment).id,
                    "debit": amount,
                    "credit": 0.0,
                    "partner_id": payment.partner_id.id,
                    "date_maturity": self.date,
                }
            )
            move_lines.append(
                {
                    "name": label,
                    "account_id": line.account_assigned_id.id,
                    "debit": 0.0,
                    "credit": amount,
                    "partner_id": payment.partner_id.id,
                }
            )
            assigned_lines |= payment._get_credit_advance_assigned_lines()
        move = self.env["account.move"].create(
            {
                "journal_id": self.journal_id.id,
                "date": self.date,
                "ref": self.env._("Unpaid effects"),
                "company_id": self.company_id.id,
                "credit_advance_line_id": line.id,
                "credit_advance_move_type": "unpaid",
                "line_ids": [(0, 0, vals) for vals in move_lines],
            }
        )
        payments._revoke_credit_advance_settlement()
        move.action_post()
        payments.write(
            {
                "credit_advance_state": "unpaid",
                "credit_advance_unpaid_move_id": move.id,
            }
        )
        self._reconcile(move, payments, assigned_lines, line)
        return {
            "type": "ir.actions.act_window",
            "res_model": "account.move",
            "view_mode": "form",
            "res_id": move.id,
        }

    def _reconcile(self, move, payments, assigned_lines, line):
        new_assigned = move.line_ids.filtered(
            lambda ml, a=line.account_assigned_id: ml.account_id == a
        )
        for partner in assigned_lines.mapped("partner_id"):
            to_reconcile = assigned_lines.filtered(
                lambda ml, p=partner: ml.partner_id == p
            ) | new_assigned.filtered(lambda ml, p=partner: ml.partner_id == p)
            if len(to_reconcile) > 1:
                to_reconcile.reconcile()
        debt_lines = move.line_ids.filtered(
            lambda ml, a=line.account_debt_id: ml.account_id == a
        )
        funding_lines = payments.payment_order_id.advance_move_id.line_ids.filtered(
            lambda ml, a=line.account_debt_id: ml.account_id == a and not ml.reconciled
        )
        if debt_lines and funding_lines:
            (debt_lines | funding_lines).reconcile()
