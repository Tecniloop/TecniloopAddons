# Copyright 2026 Tecniloop
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

import logging

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare

_logger = logging.getLogger(__name__)


class CreditAdvanceLine(models.Model):
    """Financing facility granted by a bank to advance commercial receivables.

    In the Spanish chart of accounts this is the classic "línea de anticipo de
    créditos comerciales" / "descuento comercial": the company assigns customer
    receivables to the bank, the bank advances the funds and the company keeps
    the risk until the customer effectively pays at maturity.
    """

    _name = "credit.advance.line"
    _inherit = "analytic.mixin"
    _description = "Credit Advance Line"
    _check_company_auto = True
    _order = "name"

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        comodel_name="res.company",
        required=True,
        default=lambda self: self.env.company,
    )
    currency_id = fields.Many2one(
        comodel_name="res.currency",
        related="company_id.currency_id",
        store=True,
        readonly=True,
    )
    partner_id = fields.Many2one(
        comodel_name="res.partner",
        string="Bank",
        help="Financial institution granting the facility.",
    )
    journal_id = fields.Many2one(
        comodel_name="account.journal",
        string="Bank Journal",
        required=True,
        domain="[('type', '=', 'bank')]",
        check_company=True,
        help="Journal of the bank account where the advanced funds are credited "
        "and where the charge-backs of unpaid effects are debited.",
    )
    settlement_journal_id = fields.Many2one(
        comodel_name="account.journal",
        string="Settlement Journal",
        required=True,
        domain="[('type', '=', 'general')]",
        check_company=True,
        help="Miscellaneous journal used for the entries that cancel the bank "
        "debt against the assigned receivables at maturity.",
    )
    # -- Accounts (PGC references are the Spanish general chart of accounts) --
    account_assigned_id = fields.Many2one(
        comodel_name="account.account",
        string="Assigned Receivables Account",
        required=True,
        check_company=True,
        domain="[('account_type', '=', 'asset_receivable'), ('reconcile', '=', True)]",
        help="Account holding the receivables already assigned to the bank but "
        "not yet due (PGC 4311 'Clientes, efectos comerciales descontados'). "
        "It replaces the ordinary customer account while the effect is in the "
        "hands of the bank.",
    )
    account_debt_id = fields.Many2one(
        comodel_name="account.account",
        string="Advance Debt Account",
        required=True,
        check_company=True,
        domain="[('reconcile', '=', True)]",
        help="Liability recognising the money advanced by the bank "
        "(PGC 5208 'Deudas por efectos descontados o por operaciones de "
        "factoring'). Must be reconcilable.",
    )
    account_interest_id = fields.Many2one(
        comodel_name="account.account",
        string="Interest Account",
        required=True,
        check_company=True,
        help="PGC 665 'Intereses por descuento de efectos y operaciones de "
        "factoring'.",
    )
    account_commission_id = fields.Many2one(
        comodel_name="account.account",
        string="Commission Account",
        required=True,
        check_company=True,
        help="PGC 626 'Servicios bancarios y similares'.",
    )
    account_unpaid_id = fields.Many2one(
        comodel_name="account.account",
        string="Unpaid Effects Account",
        required=True,
        check_company=True,
        domain="[('account_type', '=', 'asset_receivable'), ('reconcile', '=', True)]",
        help="PGC 4315 'Clientes, efectos comerciales impagados'. Used when the "
        "bank charges back an effect and you do not want to move the debt back "
        "to the ordinary customer account.",
    )
    outstanding_account_id = fields.Many2one(
        comodel_name="account.account",
        string="Outstanding Receipts Account",
        check_company=True,
        domain="[('reconcile', '=', True)]",
        help="Transit account used for the money advanced by the bank and for "
        "the charge-backs, so that those entries can be matched against the "
        "bank statement instead of hitting the liquidity account twice. Leave "
        "empty to use the outstanding receipts account of the bank journal, or "
        "the one of the company.",
    )
    account_unpaid_expense_id = fields.Many2one(
        comodel_name="account.account",
        string="Charge-back Expenses Account",
        check_company=True,
        help="Account for the fees invoiced by the bank on returned effects. "
        "Defaults to the commission account when empty.",
    )
    # -- Financial conditions --
    limit_amount = fields.Monetary(
        string="Facility Limit",
        currency_field="currency_id",
        help="Maximum nominal amount that may be drawn at any given time. "
        "Leave at 0 for no control.",
    )
    interest_rate = fields.Float(
        string="Annual Interest Rate (%)",
        digits=(16, 4),
        help="Used to propose the interest amount when registering the advance.",
    )
    commission_rate = fields.Float(
        string="Commission (%)",
        digits=(16, 4),
        help="Percentage over the nominal amount of the remittance.",
    )
    commission_min = fields.Monetary(
        string="Minimum Commission per Effect", currency_field="currency_id"
    )
    expense_settlement = fields.Selection(
        selection=[
            ("netted", "Deducted from the advance"),
            ("separate", "Charged separately"),
        ],
        default="netted",
        required=True,
        string="Interest and Commission Settlement",
        help="Deducted from the advance: the bank credits the nominal amount "
        "less its interest and commission, which is the usual arrangement. The "
        "statement shows a single line for the net amount.\n\n"
        "Charged separately: the bank credits the whole nominal amount and "
        "charges the interest and the commission in another movement, usually "
        "at the end of the month. The advance entry then leaves the full "
        "nominal on the outstanding account so that it matches the statement "
        "line, and the charges are booked when their own line is reconciled.",
    )
    interest_extra_days = fields.Integer(
        string="Extra Days",
        help="Value days added by the bank to the real number of days between "
        "the advance date and the maturity date.",
    )
    day_basis = fields.Selection(
        selection=[("360", "360"), ("365", "365")],
        default="360",
        required=True,
        string="Day Count Basis",
    )
    # -- Automatic settlement at maturity --
    schedule_settlement = fields.Boolean(
        string="Schedule the Settlement Entry",
        help="When the advance is registered, create the entry that cancels "
        "the debt with the bank already dated at the end of the recourse "
        "period, in draft and set to post itself on that date. The cancellation "
        "of every effect is then visible in advance, and it is revoked "
        "automatically if the bank charges the effect back before then.",
    )
    recourse_days = fields.Integer(
        string="Recourse Days",
        help="Days after the maturity date during which the bank may still "
        "charge an effect back. The risk of the customer is not released, and "
        "the effect is not settled automatically, until this period has "
        "expired. Leave at 0 to release the effect on its maturity date.",
    )
    # -- Follow up --
    payment_mode_ids = fields.One2many(
        comodel_name="account.payment.mode",
        inverse_name="credit_advance_line_id",
        string="Payment Modes",
    )
    order_ids = fields.One2many(
        comodel_name="account.payment.order",
        inverse_name="credit_advance_line_id",
        string="Remittances",
    )
    order_count = fields.Integer(compute="_compute_order_count")
    drawn_amount = fields.Monetary(
        compute="_compute_amounts",
        currency_field="currency_id",
        string="Drawn Amount",
        help="Nominal amount of the effects advanced and still pending of "
        "maturity.",
    )
    available_amount = fields.Monetary(
        compute="_compute_amounts", currency_field="currency_id"
    )
    unpaid_amount = fields.Monetary(
        compute="_compute_amounts", currency_field="currency_id"
    )

    _name_company_unique = models.Constraint(
        "unique(name, company_id)",
        "There is already a credit advance line with this name in this company!",
    )

    @api.constrains("account_debt_id")
    def _check_account_debt_reconcile(self):
        for line in self:
            if not line.account_debt_id.reconcile:
                raise ValidationError(
                    self.env._(
                        "The advance debt account %s must allow reconciliation, "
                        "otherwise the settlement of the matured effects cannot "
                        "be matched against the funds advanced by the bank.",
                        line.account_debt_id.display_name,
                    )
                )

    @api.constrains("account_assigned_id", "account_unpaid_id")
    def _check_specific_accounts(self):
        for line in self:
            for account in (line.account_assigned_id, line.account_unpaid_id):
                partner_accounts = self.env["res.partner"].search(
                    [("property_account_receivable_id", "=", account.id)],
                    limit=1,
                )
                if partner_accounts:
                    raise ValidationError(
                        self.env._(
                            "The account %s is used as the default receivable "
                            "account of at least one partner. Use a dedicated "
                            "account (PGC 4311 / 4315) instead.",
                            account.display_name,
                        )
                    )

    def _get_outstanding_account(self):
        """Account the bank movements of the facility are booked against.

        Never the liquidity account of the journal: in Odoo the statement line
        itself lands there, so booking our entry on it would double the balance
        and the entry would not show up in the reconciliation widget.
        """
        self.ensure_one()
        account = self.outstanding_account_id
        if not account:
            method_line = self.journal_id.inbound_payment_method_line_ids.filtered(
                "payment_account_id"
            )[:1]
            account = method_line.payment_account_id
        if not account:
            payment = self.env["account.payment"].with_company(self.company_id).new()
            account = payment._get_outstanding_account("inbound")
        if account == self.journal_id.default_account_id:
            raise UserError(
                self.env._(
                    "The outstanding receipts account of the credit advance "
                    "line %(line)s is the liquidity account of the journal "
                    "%(journal)s. Use a transit account instead, otherwise the "
                    "bank balance is counted twice when the statement is "
                    "reconciled.",
                    line=self.display_name,
                    journal=self.journal_id.display_name,
                )
            )
        if not account.reconcile:
            raise UserError(
                self.env._(
                    "The outstanding receipts account %(account)s used by the "
                    "credit advance line %(line)s does not allow "
                    "reconciliation, so its entries could never be matched "
                    "against the bank statement.",
                    account=account.display_name,
                    line=self.display_name,
                )
            )
        return account

    def _get_advanced_payments(self):
        """Payments already advanced and not settled/charged back yet."""
        self.ensure_one()
        return self.env["account.payment"].search(
            [
                ("credit_advance_line_id", "=", self.id),
                ("credit_advance_state", "in", ("assigned", "advanced")),
            ]
        )

    @api.depends(
        "limit_amount",
        "order_ids.payment_ids.credit_advance_state",
        "order_ids.payment_ids.credit_advance_amount",
    )
    def _compute_amounts(self):
        payment_obj = self.env["account.payment"]
        for line in self:
            groups = payment_obj._read_group(
                [
                    ("credit_advance_line_id", "=", line.id),
                    ("credit_advance_state", "in", ("assigned", "advanced", "unpaid")),
                ],
                ["credit_advance_state"],
                ["credit_advance_amount:sum"],
            )
            amounts = dict(groups)
            line.drawn_amount = amounts.get("assigned", 0.0) + amounts.get(
                "advanced", 0.0
            )
            line.unpaid_amount = amounts.get("unpaid", 0.0)
            line.available_amount = line.limit_amount - line.drawn_amount

    @api.depends("order_ids")
    def _compute_order_count(self):
        data = self.env["account.payment.order"]._read_group(
            [("credit_advance_line_id", "in", self.ids)],
            ["credit_advance_line_id"],
            ["__count"],
        )
        count_data = {line.id: count for line, count in data}
        for line in self:
            line.order_count = count_data.get(line.id, 0)

    def _check_limit(self, amount):
        """Raise nothing, just tell whether the facility limit is exceeded."""
        self.ensure_one()
        if not self.limit_amount:
            return False
        return (
            float_compare(
                self.drawn_amount + amount,
                self.limit_amount,
                precision_rounding=self.currency_id.rounding,
            )
            > 0
        )

    def _get_effects_to_settle_domain(self, date_reference):
        """Effects whose recourse period has expired without incident.

        Only funded effects: one that was assigned but never advanced means
        something is off with the remittance, and that deserves a human look
        rather than an automatic entry.
        """
        self.ensure_one()
        limit_date = date_reference - relativedelta(days=self.recourse_days)
        return [
            ("credit_advance_line_id", "=", self.id),
            ("credit_advance_state", "=", "advanced"),
            ("credit_advance_maturity_date", "!=", False),
            ("credit_advance_maturity_date", "<=", limit_date),
            ("credit_advance_settle_move_id", "=", False),
        ]

    def _get_effects_to_settle(self, date_reference=None):
        self.ensure_one()
        date_reference = date_reference or fields.Date.context_today(self)
        return self.env["account.payment"].search(
            self._get_effects_to_settle_domain(date_reference)
        )

    def _settle_effects(self, payments, date=None):
        """Run the settlement of a set of effects through the usual wizard."""
        self.ensure_one()
        wizard = self.env["credit.advance.settle"].create(
            {
                "credit_advance_line_id": self.id,
                "journal_id": self.settlement_journal_id.id,
                "date": date or fields.Date.context_today(self),
                "payment_ids": [(6, 0, payments.ids)],
            }
        )
        return wizard.action_confirm()

    def action_settle_matured_effects(self):
        """Manual trigger of the same process the scheduled action runs."""
        self.ensure_one()
        payments = self._get_effects_to_settle()
        if not payments:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "message": self.env._(
                        "No effect of %s has finished its recourse period.",
                        self.display_name,
                    ),
                    "type": "info",
                },
            }
        return self._settle_effects(payments)

    def _get_settlement_date(self, payment):
        """Date on which the effect stops being a risk for us."""
        self.ensure_one()
        maturity = payment.credit_advance_maturity_date or fields.Date.context_today(
            self
        )
        return maturity + relativedelta(days=self.recourse_days)

    def _schedule_settlement_moves(self, payments):
        """Write the settlement entries in advance, to post themselves later.

        One entry per settlement date, with every effect contributing its own
        pair of journal items. Each pair balances on its own, so revoking a
        single effect when the bank returns it is just a matter of removing its
        two lines: the entry stays balanced and the rest of the effects keep
        their appointment.
        """
        self.ensure_one()
        moves = self.env["account.move"]
        by_date = {}
        for payment in payments:
            by_date.setdefault(self._get_settlement_date(payment), []).append(payment)
        for date, date_payments in by_date.items():
            line_vals = []
            for payment in date_payments:
                line_vals += self._prepare_settlement_line_vals(payment)
            move = self.env["account.move"].create(
                {
                    "journal_id": self.settlement_journal_id.id,
                    "date": date,
                    "auto_post": "at_date",
                    "ref": self.env._("Maturity of advanced effects"),
                    "company_id": self.company_id.id,
                    "credit_advance_line_id": self.id,
                    "credit_advance_move_type": "settlement",
                    "line_ids": [(0, 0, vals) for vals in line_vals],
                }
            )
            for payment in date_payments:
                payment.credit_advance_settle_move_id = move
            moves |= move
        return moves

    def _prepare_settlement_line_vals(self, payment):
        """The two journal items that release one effect."""
        self.ensure_one()
        amount = payment.credit_advance_amount
        label = self.env._(
            "Maturity %(ref)s - %(partner)s",
            ref=payment.payment_order_id.name,
            partner=payment.partner_id.name,
        )
        return [
            {
                "name": label,
                "account_id": self.account_debt_id.id,
                "debit": amount,
                "credit": 0.0,
                "partner_id": self.partner_id.id,
                "credit_advance_payment_id": payment.id,
            },
            {
                "name": label,
                "account_id": self.account_assigned_id.id,
                "debit": 0.0,
                "credit": amount,
                "partner_id": payment.partner_id.id,
                "credit_advance_payment_id": payment.id,
            },
        ]

    def action_view_orders(self):
        self.ensure_one()
        return {
            "name": self.env._("Remittances"),
            "type": "ir.actions.act_window",
            "res_model": "account.payment.order",
            "view_mode": "list,form",
            "domain": [("credit_advance_line_id", "=", self.id)],
            "context": {"default_credit_advance_line_id": self.id},
        }

    def action_view_effects(self):
        self.ensure_one()
        return {
            "name": self.env._("Advanced Effects"),
            "type": "ir.actions.act_window",
            "res_model": "account.payment",
            "view_mode": "list,form",
            "domain": [("credit_advance_line_id", "=", self.id)],
            "context": {"search_default_credit_advance_advanced": 1},
        }
