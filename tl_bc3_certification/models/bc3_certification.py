from odoo import _, api, fields, models
from odoo.exceptions import UserError


class Bc3Certification(models.Model):
    _name = "bc3.certification"
    _description = "BC3 Certification"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "certification_number desc, id desc"

    name = fields.Char(required=True, tracking=True)
    budget_id = fields.Many2one("bc3.budget", required=True, ondelete="restrict", tracking=True)
    sale_order_id = fields.Many2one("sale.order", required=True, ondelete="restrict", tracking=True)
    company_id = fields.Many2one(related="sale_order_id.company_id", store=True)
    partner_id = fields.Many2one(related="sale_order_id.partner_id", store=True)
    currency_id = fields.Many2one(related="sale_order_id.currency_id", store=True)
    certification_number = fields.Integer(required=True, default=1, tracking=True)
    certification_date = fields.Date(default=fields.Date.context_today, required=True, tracking=True)
    previous_certification_id = fields.Many2one("bc3.certification", string="Previous Certification", readonly=True)
    state = fields.Selection(
        [("draft", "Draft"), ("confirmed", "Confirmed"), ("invoiced", "Invoiced"), ("cancelled", "Cancelled")],
        default="draft",
        required=True,
        tracking=True,
    )
    line_ids = fields.One2many("bc3.certification.line", "certification_id", string="Lines")
    invoice_ids = fields.One2many("account.move", "bc3_certification_id", string="Invoices", readonly=True)
    invoice_count = fields.Integer(compute="_compute_invoice_count")
    amount_previous = fields.Monetary(compute="_compute_amounts", store=True)
    amount_current = fields.Monetary(compute="_compute_amounts", store=True)
    amount_cumulative = fields.Monetary(compute="_compute_amounts", store=True)
    origin_bc3_file_id = fields.Many2one("bc3.file", string="Origin BC3 File")

    @api.depends("invoice_ids")
    def _compute_invoice_count(self):
        for cert in self:
            cert.invoice_count = len(cert.invoice_ids)

    @api.depends("line_ids.previous_amount", "line_ids.current_amount", "line_ids.cumulative_amount")
    def _compute_amounts(self):
        for cert in self:
            cert.amount_previous = sum(cert.line_ids.mapped("previous_amount"))
            cert.amount_current = sum(cert.line_ids.mapped("current_amount"))
            cert.amount_cumulative = sum(cert.line_ids.mapped("cumulative_amount"))

    @api.onchange("sale_order_id")
    def _onchange_sale_order_id(self):
        for cert in self:
            if cert.sale_order_id and cert.sale_order_id.bc3_budget_id:
                cert.budget_id = cert.sale_order_id.bc3_budget_id

    @api.model
    def create(self, vals):
        if vals.get("sale_order_id") and not vals.get("budget_id"):
            order = self.env["sale.order"].browse(vals["sale_order_id"])
            if order.bc3_budget_id:
                vals["budget_id"] = order.bc3_budget_id.id
        return super().create(vals)

    @api.model
    def create_from_sale_order(self, order):
        if not order.bc3_budget_id:
            raise UserError(_("The sale order is not linked to a BC3 budget."))
        previous = self.search([
            ("sale_order_id", "=", order.id),
            ("state", "in", ("confirmed", "invoiced")),
        ], order="certification_number desc, id desc", limit=1)
        number = (previous.certification_number or 0) + 1 if previous else 1
        cert = self.create({
            "name": _("Certification %(number)s - %(order)s") % {"number": number, "order": order.name},
            "budget_id": order.bc3_budget_id.id,
            "sale_order_id": order.id,
            "certification_number": number,
            "previous_certification_id": previous.id if previous else False,
        })
        cert.action_load_lines()
        order.message_post(body=_("BC3 certification %s has been created.") % cert.name)
        return cert

    def action_load_lines(self):
        for cert in self:
            if cert.state != "draft":
                raise UserError(_("Only draft certifications can be reloaded."))
            if not cert.sale_order_id:
                raise UserError(_("Select a sale order before loading certification lines."))
            cert.line_ids.unlink()
            vals = cert._prepare_certification_line_commands()
            cert.write({"line_ids": vals})
        return True

    def _prepare_certification_line_commands(self):
        self.ensure_one()
        commands = []
        sale_lines = self.sale_order_id.order_line.filtered(
            lambda line: not line.display_type and line.bc3_budget_line_id and line.bc3_budget_line_id.line_type == "work_unit"
        ).sorted(key=lambda line: (line.sequence, line.id))
        if sale_lines:
            for sale_line in sale_lines:
                budget_line = sale_line.bc3_budget_line_id
                commands.append((0, 0, self._prepare_certification_line_vals(budget_line, sale_line)))
            return commands

        sale_lines_by_budget = self._get_sale_lines_by_budget()
        for budget_line in self.budget_id.line_ids.filtered(lambda line: line.line_type == "work_unit").sorted(key=lambda line: (line.sequence, line.id)):
            sale_line = sale_lines_by_budget.get(budget_line.id)
            commands.append((0, 0, self._prepare_certification_line_vals(budget_line, sale_line)))
        return commands

    def _get_sale_lines_by_budget(self):
        self.ensure_one()
        sale_lines_by_budget = {}
        sale_lines_by_key = {}
        for sale_line in self.sale_order_id.order_line.filtered(lambda line: not line.display_type):
            budget_line = sale_line.bc3_budget_line_id
            if budget_line:
                sale_lines_by_budget[budget_line.id] = sale_line
            key = (sale_line.bc3_code or "", sale_line.bc3_position_path or "")
            if key != ("", ""):
                sale_lines_by_key[key] = sale_line
        for budget_line in self.budget_id.line_ids.filtered(lambda line: line.line_type == "work_unit"):
            if budget_line.id not in sale_lines_by_budget:
                sale_line = sale_lines_by_key.get((budget_line.code or "", budget_line.position_path or "")) or sale_lines_by_key.get((budget_line.code or "", ""))
                if sale_line:
                    sale_lines_by_budget[budget_line.id] = sale_line
        return sale_lines_by_budget

    def _prepare_certification_line_vals(self, budget_line, sale_line=False):
        self.ensure_one()
        previous_qty = self._previous_cumulative_qty(budget_line)
        sale_uom = sale_line._get_bc3_sale_uom() if sale_line else False
        return {
            "budget_line_id": budget_line.id,
            "sale_order_line_id": sale_line.id if sale_line else False,
            "bc3_code": budget_line.code,
            "name": budget_line.name,
            "uom_id": (sale_uom.id if sale_uom else budget_line.uom_id.id),
            "budget_qty": sale_line.product_uom_qty if sale_line else budget_line.quantity,
            "previous_certified_qty": previous_qty,
            "cumulative_certified_qty": previous_qty,
            "price_unit": sale_line.price_unit if sale_line else budget_line.price_unit,
        }

    def _previous_cumulative_qty(self, budget_line):
        self.ensure_one()
        if not self.previous_certification_id:
            return 0.0
        previous_line = self.previous_certification_id.line_ids.filtered(lambda line: line.budget_line_id == budget_line)[:1]
        return previous_line.cumulative_certified_qty if previous_line else 0.0

    def action_open_sale_order(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Sale Order"),
            "res_model": "sale.order",
            "view_mode": "form",
            "res_id": self.sale_order_id.id,
        }

    def action_confirm(self):
        for cert in self:
            if cert.state != "draft":
                continue
            cert.state = "confirmed"
            cert.sale_order_id.order_line._compute_bc3_certification_values()
            cert.sale_order_id.message_post(body=_("BC3 certification %s has been confirmed.") % cert.name)
        return True

    def action_create_invoice(self):
        self.ensure_one()
        if self.state not in ("confirmed", "draft"):
            raise UserError(_("Only draft or confirmed certifications can be invoiced."))
        invoice_lines = []
        for line in self.line_ids.filtered(lambda item: item.current_certified_qty):
            invoice_lines.append((0, 0, line._prepare_invoice_line_vals()))
        if not invoice_lines:
            raise UserError(_("There are no current quantities to invoice."))
        move = self.env["account.move"].create({
            "move_type": "out_invoice",
            "partner_id": self.sale_order_id.partner_invoice_id.id,
            "invoice_origin": "%s - %s" % (self.sale_order_id.name, self.name),
            "invoice_date": self.certification_date,
            "currency_id": self.currency_id.id,
            "invoice_user_id": self.sale_order_id.user_id.id,
            "company_id": self.company_id.id,
            "bc3_certification_id": self.id,
            "invoice_line_ids": invoice_lines,
        })
        cert_lines_by_key = {(line.bc3_code, line.sale_order_line_id.id): line for line in self.line_ids}
        cert_lines_by_code = {line.bc3_code: line for line in self.line_ids}
        for move_line in move.invoice_line_ids:
            sale_line = move_line.sale_line_ids[:1] if "sale_line_ids" in move_line._fields else False
            cert_line = cert_lines_by_key.get((move_line.bc3_code, sale_line.id if sale_line else False)) or cert_lines_by_code.get(move_line.bc3_code)
            if cert_line:
                cert_line.invoice_line_id = move_line.id
        self.state = "invoiced"
        self.sale_order_id.order_line._compute_bc3_certification_values()
        self.sale_order_id.message_post(body=_("BC3 certification %(cert)s has been invoiced in %(invoice)s.") % {"cert": self.name, "invoice": move.name or move.ref or move.id})
        return {
            "type": "ir.actions.act_window",
            "name": _("Invoice"),
            "res_model": "account.move",
            "view_mode": "form",
            "res_id": move.id,
        }

    def action_open_invoices(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Invoices"),
            "res_model": "account.move",
            "view_mode": "list,form",
            "domain": [("bc3_certification_id", "=", self.id)],
        }

    def action_cancel(self):
        for cert in self:
            cert.state = "cancelled"
        return True


class Bc3CertificationLine(models.Model):
    _name = "bc3.certification.line"
    _description = "BC3 Certification Line"
    _order = "certification_id, budget_line_id"

    certification_id = fields.Many2one("bc3.certification", required=True, ondelete="cascade", index=True)
    budget_id = fields.Many2one(related="certification_id.budget_id", store=True)
    sale_order_id = fields.Many2one(related="certification_id.sale_order_id", store=True)
    currency_id = fields.Many2one(related="certification_id.currency_id", store=True)
    budget_line_id = fields.Many2one("bc3.budget.line", required=True, ondelete="restrict", index=True)
    sale_order_line_id = fields.Many2one("sale.order.line", ondelete="restrict", index=True)
    bc3_code = fields.Char(required=True, index=True)
    name = fields.Char(required=True)
    uom_id = fields.Many2one("uom.uom")
    budget_qty = fields.Float(digits="Product Unit of Measure")
    previous_certified_qty = fields.Float(readonly=True, digits="Product Unit of Measure")
    current_certified_qty = fields.Float(compute="_compute_current", inverse="_inverse_current", store=True, digits="Product Unit of Measure")
    cumulative_certified_qty = fields.Float(digits="Product Unit of Measure")
    remaining_qty = fields.Float(compute="_compute_remaining", store=True, digits="Product Unit of Measure")
    price_unit = fields.Float(digits="Product Price")
    previous_amount = fields.Monetary(compute="_compute_amounts", store=True)
    current_amount = fields.Monetary(compute="_compute_amounts", store=True)
    cumulative_amount = fields.Monetary(compute="_compute_amounts", store=True)
    invoice_line_id = fields.Many2one("account.move.line", readonly=True, copy=False)

    @api.depends("cumulative_certified_qty", "previous_certified_qty")
    def _compute_current(self):
        for line in self:
            line.current_certified_qty = (line.cumulative_certified_qty or 0.0) - (line.previous_certified_qty or 0.0)

    def _inverse_current(self):
        for line in self:
            line.cumulative_certified_qty = (line.previous_certified_qty or 0.0) + (line.current_certified_qty or 0.0)

    @api.depends("budget_qty", "cumulative_certified_qty")
    def _compute_remaining(self):
        for line in self:
            line.remaining_qty = (line.budget_qty or 0.0) - (line.cumulative_certified_qty or 0.0)

    @api.depends("previous_certified_qty", "current_certified_qty", "cumulative_certified_qty", "price_unit")
    def _compute_amounts(self):
        for line in self:
            line.previous_amount = (line.previous_certified_qty or 0.0) * (line.price_unit or 0.0)
            line.current_amount = (line.current_certified_qty or 0.0) * (line.price_unit or 0.0)
            line.cumulative_amount = (line.cumulative_certified_qty or 0.0) * (line.price_unit or 0.0)

    def _prepare_invoice_line_vals(self):
        self.ensure_one()
        sale_line = self.sale_order_line_id
        product = sale_line.product_id if sale_line else self.env.ref("tl_bc3_sale.product_bc3_work_unit", raise_if_not_found=False)
        account = self._get_income_account(product)
        if not account:
            raise UserError(_("No income account could be found for BC3 certification line %s.") % self.bc3_code)
        vals = {
            "name": "[%s] %s" % (self.bc3_code, self.name),
            "quantity": self.current_certified_qty,
            "price_unit": self.price_unit,
            "account_id": account.id,
            "bc3_certification_line_id": self.id,
            "bc3_budget_line_id": self.budget_line_id.id,
            "bc3_code": self.bc3_code,
            "bc3_cumulative_qty": self.cumulative_certified_qty,
        }
        if product:
            vals["product_id"] = product.id
        if self.uom_id and "product_uom_id" in self.env["account.move.line"]._fields:
            vals["product_uom_id"] = self.uom_id.id
        if sale_line and "sale_line_ids" in self.env["account.move.line"]._fields:
            vals["sale_line_ids"] = [(6, 0, [sale_line.id])]
        taxes = self._get_sale_line_taxes(sale_line)
        if taxes and "tax_ids" in self.env["account.move.line"]._fields:
            vals["tax_ids"] = [(6, 0, taxes.ids)]
        return vals

    def _get_sale_line_taxes(self, sale_line):
        if not sale_line:
            product = self.sale_order_line_id.product_id if self.sale_order_line_id else False
            return product.taxes_id.filtered(lambda tax: tax.company_id == self.certification_id.company_id or not tax.company_id) if product else self.env["account.tax"]
        if "tax_ids" in sale_line._fields:
            return sale_line.tax_ids
        if "tax_id" in sale_line._fields:
            return sale_line.tax_id
        return self.env["account.tax"]

    def _get_income_account(self, product):
        if product:
            accounts = product.product_tmpl_id._get_product_accounts()
            return accounts.get("income")
        return False


class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"

    def _compute_bc3_certification_values(self):
        for line in self:
            cert_lines = self.env["bc3.certification.line"].search([
                ("sale_order_line_id", "=", line.id),
                ("certification_id.state", "in", ("confirmed", "invoiced")),
            ])
            line.bc3_certified_qty = sum(cert_lines.mapped("current_certified_qty"))
            line.bc3_certified_amount = sum(cert_lines.mapped("current_amount"))
