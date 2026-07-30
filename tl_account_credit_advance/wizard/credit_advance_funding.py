# Copyright 2026 Tecniloop
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

from odoo import api, fields, models
from odoo.exceptions import UserError


class CreditAdvanceFunding(models.TransientModel):
    """Books the settlement note sent by the bank when it advances a remittance.

        (572) Bank                  net amount
        (665) Interest              interest
        (626) Commission            commission + other expenses
                to (5208) Debt for discounted effects    nominal

    The customer receivables are *not* touched here: they were already moved to
    the assigned receivables account (4311) when the remittance was confirmed.
    """

    _name = "credit.advance.funding"
    _description = "Register Bank Advance"

    order_id = fields.Many2one(
        comodel_name="account.payment.order",
        string="Remittance",
        required=True,
        readonly=True,
    )
    credit_advance_line_id = fields.Many2one(
        comodel_name="credit.advance.line",
        related="order_id.credit_advance_line_id",
        readonly=True,
    )
    company_id = fields.Many2one(related="order_id.company_id", readonly=True)
    currency_id = fields.Many2one(
        related="order_id.company_currency_id", readonly=True
    )
    date = fields.Date(
        string="Value Date", required=True, default=fields.Date.context_today
    )
    journal_id = fields.Many2one(
        comodel_name="account.journal",
        string="Bank Journal",
        required=True,
        domain="[('type', 'in', ('bank', 'general')), ('company_id', '=', company_id)]",
    )
    nominal_amount = fields.Monetary(
        string="Nominal Amount", currency_field="currency_id", readonly=True
    )
    interest_amount = fields.Monetary(string="Interest", currency_field="currency_id")
    commission_amount = fields.Monetary(
        string="Commission", currency_field="currency_id"
    )
    other_expenses = fields.Monetary(
        string="Other Expenses", currency_field="currency_id"
    )
    net_amount = fields.Monetary(
        string="Net Amount", compute="_compute_net_amount", currency_field="currency_id"
    )
    reference = fields.Char(string="Bank Reference")
    expense_settlement = fields.Selection(
        related="credit_advance_line_id.expense_settlement", readonly=True
    )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        order = self.env["account.payment.order"].browse(res.get("order_id"))
        if not order:
            return res
        line = order.credit_advance_line_id
        res["nominal_amount"] = order.total_company_currency
        res.setdefault("journal_id", line.journal_id.id or order.journal_id.id)
        date = res.get("date") or fields.Date.context_today(self)
        res["interest_amount"] = self._compute_proposed_interest(order, date)
        res["commission_amount"] = self._compute_proposed_commission(order)
        return res

    @api.model
    def _compute_proposed_interest(self, order, date):
        """Simple interest over the nominal amount of every effect.

        interest = nominal * rate/100 * days / basis, where days is the real
        number of days between the value date and the maturity date of each
        effect, plus the value days charged by the bank.
        """
        line = order.credit_advance_line_id
        if line.expense_settlement == "separate" or not line.interest_rate:
            return 0.0
        basis = float(line.day_basis or "360")
        total = 0.0
        for payment in order.payment_ids:
            maturity = payment.credit_advance_maturity_date or date
            days = (maturity - date).days + line.interest_extra_days
            days = max(days, 0)
            total += payment.credit_advance_amount * line.interest_rate / 100 * (
                days / basis
            )
        return order.company_currency_id.round(total)

    @api.model
    def _compute_proposed_commission(self, order):
        line = order.credit_advance_line_id
        if line.expense_settlement == "separate":
            return 0.0
        currency = order.company_currency_id
        total = 0.0
        for payment in order.payment_ids:
            commission = payment.credit_advance_amount * line.commission_rate / 100
            total += max(commission, line.commission_min)
        return currency.round(total)

    @api.depends(
        "nominal_amount", "interest_amount", "commission_amount", "other_expenses"
    )
    def _compute_net_amount(self):
        for wizard in self:
            wizard.net_amount = (
                wizard.nominal_amount
                - wizard.interest_amount
                - wizard.commission_amount
                - wizard.other_expenses
            )

    @api.onchange("date")
    def _onchange_date(self):
        if self.order_id and self.date:
            self.interest_amount = self._compute_proposed_interest(
                self.order_id, self.date
            )

    def _get_debt_maturity_date(self):
        self.ensure_one()
        dates = [
            date
            for date in self.order_id.payment_ids.mapped(
                "credit_advance_maturity_date"
            )
            if date
        ]
        return max(dates) if dates else self.date

    def _prepare_move_lines(self):
        self.ensure_one()
        line = self.credit_advance_line_id
        label = self.env._("Advance %s", self.order_id.name)
        vals = [
            {
                "name": label,
                "account_id": line._get_outstanding_account().id,
                "debit": self.net_amount,
                "credit": 0.0,
                "partner_id": line.partner_id.id,
            },
            {
                "name": self.env._("Financial debt %s", self.order_id.name),
                "account_id": line.account_debt_id.id,
                "debit": 0.0,
                "credit": self.nominal_amount,
                "partner_id": line.partner_id.id,
                "date_maturity": self._get_debt_maturity_date(),
            },
        ]
        if self.interest_amount:
            vals.append(
                {
                    "name": self.env._("Interest %s", self.order_id.name),
                    "account_id": line.account_interest_id.id,
                    "debit": self.interest_amount,
                    "credit": 0.0,
                    "partner_id": line.partner_id.id,
                    "analytic_distribution": line.analytic_distribution,
                }
            )
        expenses = self.commission_amount + self.other_expenses
        if expenses:
            vals.append(
                {
                    "name": self.env._("Commission %s", self.order_id.name),
                    "account_id": line.account_commission_id.id,
                    "debit": expenses,
                    "credit": 0.0,
                    "partner_id": line.partner_id.id,
                    "analytic_distribution": line.analytic_distribution,
                }
            )
        return vals

    def action_confirm(self):
        self.ensure_one()
        order = self.order_id
        if order.advance_move_id:
            raise UserError(
                self.env._("The remittance %s has already been advanced.", order.name)
            )
        if self.net_amount < 0:
            raise UserError(
                self.env._(
                    "The interest and expenses exceed the nominal amount of the "
                    "remittance."
                )
            )
        move = self.env["account.move"].create(
            {
                "journal_id": self.journal_id.id,
                "date": self.date,
                "ref": self.reference or order.name,
                "company_id": order.company_id.id,
                "payment_order_id": order.id,
                "credit_advance_line_id": self.credit_advance_line_id.id,
                "credit_advance_move_type": "funding",
                "line_ids": [(0, 0, vals) for vals in self._prepare_move_lines()],
            }
        )
        move.action_post()
        order.write(
            {
                "advance_move_id": move.id,
                "advance_date": self.date,
                "advance_interest": self.interest_amount,
                "advance_commission": self.commission_amount,
                "advance_other_expenses": self.other_expenses,
            }
        )
        order.payment_ids.write({"credit_advance_state": "advanced"})
        if self.credit_advance_line_id.schedule_settlement:
            self.credit_advance_line_id._schedule_settlement_moves(order.payment_ids)
        order.message_post(
            body=self.env._(
                "Bank advance registered: %(net)s received, %(nominal)s of "
                "financial debt.",
                net=self.net_amount,
                nominal=self.nominal_amount,
            )
        )
        return {
            "type": "ir.actions.act_window",
            "res_model": "account.move",
            "view_mode": "form",
            "res_id": move.id,
        }
