# Copyright (C) 2017-2021 Creu Blanca
# Copyright (C) 2024 Tecnativa <https://tecnativa.com>
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html).

from odoo import _, api, fields, models
from odoo.exceptions import UserError

ALLOWED_TYPES = {
    "customer": ["out_invoice", "in_refund"],
    "vendor": ["in_invoice", "out_refund"],
}


class CashPayInvoice(models.TransientModel):
    _name = "cash.pay.invoice"
    _description = "Cash Pay invoice from bank statement"
    _check_company_auto = True

    def _get_active_journal(self):
        active_ids = self.env.context.get("active_ids") or []
        active_id = self.env.context.get("active_id")
        if not active_ids and active_id:
            active_ids = [active_id]
        return self.env["account.journal"].browse(active_ids[:1])

    def _default_company(self):
        journal = self._get_active_journal()
        return journal.company_id or self.env.company

    def _default_currency(self):
        journal = self._get_active_journal()
        company = journal.company_id or self.env.company
        return journal.currency_id or company.currency_id

    def _default_journal(self):
        return self._get_active_journal()

    invoice_id = fields.Many2one(
        comodel_name="account.move",
        string="Invoice",
        required=True,
        compute="_compute_invoice_id",
        store=True,
        readonly=False,
        check_company=True,
    )
    name = fields.Char(related="invoice_id.name", readonly=True)
    company_id = fields.Many2one(
        comodel_name="res.company",
        default=lambda self: self._default_company(),
        required=True,
        readonly=True,
    )
    currency_id = fields.Many2one(
        comodel_name="res.currency",
        default=lambda self: self._default_currency(),
        required=True,
        readonly=True,
    )
    journal_id = fields.Many2one(
        comodel_name="account.journal",
        required=True,
        readonly=True,
        default=lambda self: self._default_journal(),
        string="Journal",
        check_company=True,
    )
    amount = fields.Monetary(compute="_compute_amount", store=True, readonly=False)
    invoice_type = fields.Selection(
        [
            ("customer", "Customer"),
            ("vendor", "Vendor"),
        ],
    )
    invoice_domain = fields.Binary(compute="_compute_invoice_domain")

    @api.depends("company_id", "currency_id", "invoice_type")
    def _compute_invoice_domain(self):
        for wizard in self:
            invoice_domain = [
                ("company_id", "=", wizard.company_id.id),
                ("currency_id", "=", wizard.currency_id.id),
                ("state", "=", "posted"),
                ("payment_state", "!=", "paid"),
            ]
            if wizard.invoice_type:
                invoice_domain.append(
                    ("move_type", "in", ALLOWED_TYPES.get(wizard.invoice_type, []))
                )
            else:
                # Avoid selecting an invoice before the type is chosen.
                invoice_domain.append(("move_type", "in", []))
            wizard.invoice_domain = invoice_domain

    @api.depends("invoice_type")
    def _compute_invoice_id(self):
        for wizard in self:
            allowed_types = ALLOWED_TYPES.get(wizard.invoice_type, [])
            if wizard.invoice_id.move_type and wizard.invoice_id.move_type not in allowed_types:
                wizard.invoice_id = False

    @api.depends("invoice_id")
    def _compute_amount(self):
        for wizard in self:
            wizard.amount = wizard.invoice_id.amount_residual_signed

    def action_pay_invoice(self):
        BankStatementLine = self.env["account.bank.statement.line"]
        statement_line_vals = self._prepare_statement_line_vals()
        new_statement_line = BankStatementLine.create(statement_line_vals)
        lines_to_reconcile = (
            new_statement_line.invoice_id.line_ids | new_statement_line.move_id.line_ids
        ).filtered(
            lambda line: line.account_id.account_type
            in ("asset_receivable", "liability_payable")
            and not line.reconciled
        )
        lines_to_reconcile.reconcile()

    def _prepare_statement_line_vals(self):
        self.ensure_one()
        counterpart_move_lines = self.invoice_id.line_ids.filtered(
            lambda line: line.account_id.account_type
            in ("asset_receivable", "liability_payable")
            and not line.reconciled
        )
        if not counterpart_move_lines:
            raise UserError(_("There is no open receivable/payable line to reconcile."))
        counterpart_account = counterpart_move_lines[:1].account_id
        return {
            "date": fields.Date.context_today(self),
            "journal_id": self.journal_id.id,
            "amount": self.amount,
            "payment_ref": self.name,
            "invoice_id": self.invoice_id.id,
            "ref": self.invoice_id.name,
            "partner_id": self.invoice_id.partner_id.id,
            "counterpart_account_id": counterpart_account.id,
        }
