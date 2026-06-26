from odoo import _, api, fields, models
from odoo.exceptions import UserError


class Bc3Certification(models.Model):
    _name = "bc3.certification"
    _description = "Certificación BC3"
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
    previous_certification_id = fields.Many2one("bc3.certification", string="Certificación anterior", readonly=True)
    certification_method = fields.Selection(
        [
            ("quantity", "Por cantidad acumulada"),
            ("line_percent", "Por porcentaje acumulado por línea"),
            ("global_percent", "Por porcentaje global acumulado"),
        ],
        string="Método de certificación",
        default="quantity",
        required=True,
        tracking=True,
    )
    global_percent = fields.Float(string="% global acumulado", default=0.0, tracking=True)
    state = fields.Selection(
        [("draft", "Borrador"), ("confirmed", "Confirmada"), ("invoiced", "Facturada"), ("cancelled", "Cancelada")],
        default="draft",
        required=True,
        tracking=True,
    )
    line_ids = fields.One2many("bc3.certification.line", "certification_id", string="Líneas")
    invoice_ids = fields.One2many("account.move", "bc3_certification_id", string="Facturas", readonly=True)
    invoice_count = fields.Integer(compute="_compute_invoice_count")
    tax_ids = fields.Many2many(
        "account.tax",
        "bc3_certification_account_tax_rel",
        "certification_id",
        "tax_id",
        string="Impuestos",
        domain="[('type_tax_use', '=', 'sale'), '|', ('company_id', '=', False), ('company_id', '=', company_id)]",
    )
    award_discount_percent = fields.Float(string="Baja / alza de adjudicación %", default=0.0, tracking=True)
    retention_warranty_percent = fields.Float(string="Retención de garantía %", default=0.0, tracking=True)
    retention_fiscal_percent = fields.Float(string="Retención fiscal %", default=0.0, tracking=True)
    amount_previous = fields.Monetary(compute="_compute_amounts", store=True, string="Importe bruto anterior")
    amount_current = fields.Monetary(compute="_compute_amounts", store=True, string="Importe bruto actual")
    amount_cumulative = fields.Monetary(compute="_compute_amounts", store=True, string="Importe bruto acumulado")
    gross_amount_origin = fields.Monetary(compute="_compute_amounts", store=True, string="Ejecución material a origen")
    award_discount_amount = fields.Monetary(compute="_compute_amounts", store=True, string="Importe baja / alza")
    net_amount_origin = fields.Monetary(compute="_compute_amounts", store=True, string="Ejecución después de baja")
    previous_amount_origin = fields.Monetary(compute="_compute_amounts", store=True, string="Certificación anterior a deducir")
    current_base_amount = fields.Monetary(compute="_compute_amounts", store=True, string="Base imponible actual")
    tax_amount = fields.Monetary(compute="_compute_amounts", store=True, string="Importe impuestos")
    retention_warranty_amount = fields.Monetary(compute="_compute_amounts", store=True, string="Importe retención garantía")
    retention_fiscal_amount = fields.Monetary(compute="_compute_amounts", store=True, string="Importe retención fiscal")
    total_amount = fields.Monetary(compute="_compute_amounts", store=True, string="Total a pagar")
    origin_bc3_file_id = fields.Many2one("bc3.file", string="Fichero BC3 de origen")

    @api.depends("invoice_ids")
    def _compute_invoice_count(self):
        for cert in self:
            cert.invoice_count = len(cert.invoice_ids)

    @api.depends(
        "line_ids.previous_amount",
        "line_ids.current_amount",
        "line_ids.cumulative_amount",
        "award_discount_percent",
        "retention_warranty_percent",
        "retention_fiscal_percent",
        "previous_certification_id.net_amount_origin",
        "tax_ids",
    )
    def _compute_amounts(self):
        product = self.env.ref("tl_bc3_sale.product_bc3_work_unit", raise_if_not_found=False)
        for cert in self:
            amount_previous = sum(cert.line_ids.mapped("previous_amount"))
            amount_current = sum(cert.line_ids.mapped("current_amount"))
            amount_cumulative = sum(cert.line_ids.mapped("cumulative_amount"))
            cert.amount_previous = amount_previous
            cert.amount_current = amount_current
            cert.amount_cumulative = amount_cumulative
            cert.gross_amount_origin = amount_cumulative
            cert.award_discount_amount = amount_cumulative * (cert.award_discount_percent or 0.0) / 100.0
            cert.net_amount_origin = amount_cumulative - cert.award_discount_amount
            cert.previous_amount_origin = cert.previous_certification_id.net_amount_origin if cert.previous_certification_id else 0.0
            cert.current_base_amount = cert.net_amount_origin - cert.previous_amount_origin
            cert.retention_warranty_amount = cert.current_base_amount * (cert.retention_warranty_percent or 0.0) / 100.0
            cert.retention_fiscal_amount = cert.current_base_amount * (cert.retention_fiscal_percent or 0.0) / 100.0
            cert.tax_amount = cert._compute_tax_amount(cert.current_base_amount, product)
            cert.total_amount = cert.current_base_amount + cert.tax_amount - cert.retention_warranty_amount - cert.retention_fiscal_amount

    def _compute_tax_amount(self, base_amount, product=False):
        self.ensure_one()
        if not self.tax_ids:
            return 0.0
        taxes_res = self.tax_ids.compute_all(
            base_amount,
            currency=self.currency_id,
            quantity=1.0,
            product=product,
            partner=self.partner_id,
        )
        return taxes_res.get("total_included", 0.0) - taxes_res.get("total_excluded", 0.0)

    @api.onchange("sale_order_id")
    def _onchange_sale_order_id(self):
        for cert in self:
            if cert.sale_order_id and cert.sale_order_id.bc3_budget_id:
                cert.budget_id = cert.sale_order_id.bc3_budget_id
                cert.tax_ids = cert._get_default_taxes_from_order(cert.sale_order_id)

    @api.model_create_multi
    def create(self, vals_list):
        """Create certifications using the Odoo 19 multi-create API.

        Odoo 19 always calls create with a list of dictionaries.  The
        previous implementation expected a single dictionary and failed with
        ``AttributeError: 'list' object has no attribute 'get'`` when a
        certification was created from a sale order.
        """
        if isinstance(vals_list, dict):
            vals_list = [vals_list]
        for vals in vals_list:
            if vals.get("sale_order_id") and not vals.get("budget_id"):
                order = self.env["sale.order"].browse(vals["sale_order_id"])
                if order.bc3_budget_id:
                    vals["budget_id"] = order.bc3_budget_id.id
            if vals.get("sale_order_id") and not vals.get("tax_ids"):
                taxes = self._get_default_taxes_from_order(self.env["sale.order"].browse(vals["sale_order_id"]))
                if taxes:
                    vals["tax_ids"] = [(6, 0, taxes.ids)]
        return super().create(vals_list)

    @api.model
    def create_from_sale_order(self, order):
        if not order.bc3_budget_id:
            raise UserError(_("El pedido de venta no está vinculado a un presupuesto BC3."))
        previous = self.search([
            ("sale_order_id", "=", order.id),
            ("state", "in", ("confirmed", "invoiced")),
        ], order="certification_number desc, id desc", limit=1)
        number = (previous.certification_number or 0) + 1 if previous else 1
        taxes = self._get_default_taxes_from_order(order)
        vals = {
            "name": _("Certificación %(number)s - %(order)s") % {"number": number, "order": order.name},
            "budget_id": order.bc3_budget_id.id,
            "sale_order_id": order.id,
            "certification_number": number,
            "previous_certification_id": previous.id if previous else False,
        }
        if taxes:
            vals["tax_ids"] = [(6, 0, taxes.ids)]
        cert = self.create(vals)
        cert.action_load_lines()
        order.message_post(body=_("Se ha creado la certificación BC3 %s.") % cert.name)
        return cert

    @api.model
    def _get_default_taxes_from_order(self, order):
        taxes = self.env["account.tax"]
        if not order:
            return taxes
        for sale_line in order.order_line.filtered(lambda line: not line.display_type):
            if "tax_ids" in sale_line._fields and sale_line.tax_ids:
                return sale_line.tax_ids
            if "tax_id" in sale_line._fields and sale_line.tax_id:
                return sale_line.tax_id
        product = self.env.ref("tl_bc3_sale.product_bc3_work_unit", raise_if_not_found=False)
        if product:
            taxes = product.taxes_id.filtered(lambda tax: tax.company_id == order.company_id or not tax.company_id)
        return taxes

    def action_load_lines(self):
        for cert in self:
            if cert.state != "draft":
                raise UserError(_("Solo se pueden recargar certificaciones en borrador."))
            if not cert.sale_order_id:
                raise UserError(_("Selecciona un pedido de venta antes de cargar las líneas de certificación."))
            cert.line_ids.unlink()
            vals = cert._prepare_certification_line_commands()
            cert.write({"line_ids": vals})
        return True

    def action_apply_global_percent(self):
        for cert in self:
            if cert.state != "draft":
                raise UserError(_("El porcentaje global solo puede aplicarse en certificaciones en borrador."))
            for line in cert.line_ids:
                line.cumulative_certified_qty = (line.budget_qty or 0.0) * (cert.global_percent or 0.0) / 100.0
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

    def _get_income_account(self, product):
        if product:
            accounts = product.product_tmpl_id._get_product_accounts()
            return accounts.get("income")
        return False

    def _get_certification_product(self):
        return self.env.ref("tl_bc3_sale.product_bc3_work_unit", raise_if_not_found=False)

    def action_open_sale_order(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Pedido de venta"),
            "res_model": "sale.order",
            "view_mode": "form",
            "res_id": self.sale_order_id.id,
        }

    def action_confirm(self):
        for cert in self:
            if cert.state != "draft":
                continue
            if cert.current_base_amount <= 0:
                raise UserError(_("El importe actual de la certificación debe ser mayor que cero."))
            cert.state = "confirmed"
            cert.sale_order_id.order_line._compute_bc3_certification_values()
            cert.sale_order_id.message_post(body=_("Se ha confirmado la certificación BC3 %s.") % cert.name)
        return True

    def action_create_invoice(self):
        self.ensure_one()
        if self.state not in ("confirmed", "draft"):
            raise UserError(_("Solo se pueden facturar certificaciones en borrador o confirmadas."))
        if self.current_base_amount <= 0:
            raise UserError(_("No hay importe positivo que facturar para esta certificación."))
        invoice_lines = self._prepare_origin_invoice_line_commands()
        if not invoice_lines:
            raise UserError(_("No hay importes que facturar."))
        move_vals = {
            "move_type": "out_invoice",
            "partner_id": self.sale_order_id.partner_invoice_id.id,
            "invoice_origin": "%s - %s" % (self.sale_order_id.name, self.name),
            "invoice_date": self.certification_date,
            "currency_id": self.currency_id.id,
            "invoice_user_id": self.sale_order_id.user_id.id,
            "company_id": self.company_id.id,
            "bc3_certification_id": self.id,
            "invoice_line_ids": invoice_lines,
        }
        if "invoice_payment_term_id" in self.env["account.move"]._fields and self.sale_order_id.payment_term_id:
            move_vals["invoice_payment_term_id"] = self.sale_order_id.payment_term_id.id
        move = self.env["account.move"].create(move_vals)
        self.line_ids.filtered(lambda line: line.current_certified_qty).write({"invoice_line_id": False})
        self.state = "invoiced"
        self.sale_order_id.order_line._compute_bc3_certification_values()
        self.sale_order_id.message_post(body=_("La certificación BC3 %(cert)s se ha facturado en %(invoice)s.") % {"cert": self.name, "invoice": move.name or move.ref or move.id})
        return {
            "type": "ir.actions.act_window",
            "name": _("Factura"),
            "res_model": "account.move",
            "view_mode": "form",
            "res_id": move.id,
        }

    def _prepare_origin_invoice_line_commands(self):
        self.ensure_one()
        product = self._get_certification_product()
        account = self._get_income_account(product)
        if not account:
            raise UserError(_("No se ha encontrado cuenta de ingresos para el producto de certificación BC3."))
        commands = []
        for chapter in self._get_report_chapter_lines():
            if not chapter["amount"]:
                continue
            vals = self._prepare_account_move_line_vals(
                name="[%s] %s" % (chapter["code"], chapter["name"]),
                amount=chapter["amount"],
                account=account,
                product=product,
                taxes=True,
                code=chapter["code"],
                cumulative_qty=0.0,
            )
            commands.append((0, 0, vals))
        if self.award_discount_amount:
            commands.append((0, 0, self._prepare_account_move_line_vals(
                name=_("%(percent).2f%% Baja / alza de adjudicación") % {"percent": self.award_discount_percent},
                amount=-self.award_discount_amount,
                account=account,
                product=product,
                taxes=True,
                code="BAJA",
            )))
        if self.previous_amount_origin:
            commands.append((0, 0, self._prepare_account_move_line_vals(
                name=_("A deducir certificación anterior %(number)s") % {"number": self.previous_certification_id.certification_number},
                amount=-self.previous_amount_origin,
                account=account,
                product=product,
                taxes=True,
                code="PREV",
            )))
        if self.retention_warranty_amount:
            commands.append((0, 0, self._prepare_account_move_line_vals(
                name=_("Retención de garantía"),
                amount=-self.retention_warranty_amount,
                account=account,
                product=product,
                taxes=False,
                code="RET-W",
            )))
        if self.retention_fiscal_amount:
            commands.append((0, 0, self._prepare_account_move_line_vals(
                name=_("Retención fiscal"),
                amount=-self.retention_fiscal_amount,
                account=account,
                product=product,
                taxes=False,
                code="RET-F",
            )))
        return commands

    def _prepare_account_move_line_vals(self, name, amount, account, product=False, taxes=True, code=False, cumulative_qty=0.0):
        self.ensure_one()
        vals = {
            "name": name,
            "quantity": 1.0,
            "price_unit": amount,
            "account_id": account.id,
            "bc3_code": code,
            "bc3_cumulative_qty": cumulative_qty,
        }
        if product:
            vals["product_id"] = product.id
        if taxes and self.tax_ids and "tax_ids" in self.env["account.move.line"]._fields:
            vals["tax_ids"] = [(6, 0, self.tax_ids.ids)]
        return vals

    def _get_report_chapter_lines(self):
        self.ensure_one()
        summaries = {}
        order = []
        for line in self.line_ids:
            chapter = self._get_chapter_line(line.budget_line_id)
            key = chapter.id if chapter else 0
            if key not in summaries:
                summaries[key] = {
                    "sequence": chapter.sequence if chapter else 0,
                    "code": chapter.code if chapter else _("Sin capítulo"),
                    "name": chapter.name if chapter else _("Sin capítulo"),
                    "amount": 0.0,
                    "percent": 0.0,
                }
                order.append(key)
            summaries[key]["amount"] += line.cumulative_amount or 0.0
        total = sum(item["amount"] for item in summaries.values())
        for item in summaries.values():
            item["percent"] = (item["amount"] / total * 100.0) if total else 0.0
        return [summaries[key] for key in sorted(order, key=lambda key: summaries[key]["sequence"])]

    def _get_chapter_line(self, budget_line):
        line = budget_line
        while line and line.line_type not in ("chapter", "root"):
            line = line.parent_id
        return line

    def _format_report_amount(self, amount):
        return ("%0.2f" % (amount or 0.0)).replace(".", ",")

    def _format_report_percent(self, amount):
        return ("%0.2f" % (amount or 0.0)).replace(".", ",")

    def _get_amount_total_text(self):
        self.ensure_one()
        if not self.currency_id:
            return ""
        try:
            return self.currency_id.amount_to_text(self.total_amount)
        except Exception:
            return ""

    def action_open_invoices(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Facturas"),
            "res_model": "account.move",
            "view_mode": "list,form",
            "domain": [("bc3_certification_id", "=", self.id)],
        }

    def _sync_invoice_state_from_invoices(self):
        for cert in self.exists():
            active_invoices = cert.invoice_ids.exists().filtered(lambda move: move.state != "cancel")
            if active_invoices:
                if cert.state != "invoiced":
                    cert.state = "invoiced"
            elif cert.state == "invoiced":
                cert.state = "confirmed"
        return True

    def action_cancel(self):
        for cert in self:
            cert.state = "cancelled"
        return True


class Bc3CertificationLine(models.Model):
    _name = "bc3.certification.line"
    _description = "Línea de certificación BC3"
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
    previous_percent = fields.Float(compute="_compute_percentages", store=True, string="% anterior")
    current_percent = fields.Float(compute="_compute_percentages", store=True, string="% actual")
    cumulative_percent = fields.Float(compute="_compute_percentages", inverse="_inverse_cumulative_percent", store=True, string="% acumulado")
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

    @api.depends("budget_qty", "previous_certified_qty", "current_certified_qty", "cumulative_certified_qty")
    def _compute_percentages(self):
        for line in self:
            qty = line.budget_qty or 0.0
            if qty:
                line.previous_percent = (line.previous_certified_qty or 0.0) / qty * 100.0
                line.current_percent = (line.current_certified_qty or 0.0) / qty * 100.0
                line.cumulative_percent = (line.cumulative_certified_qty or 0.0) / qty * 100.0
            else:
                line.previous_percent = 0.0
                line.current_percent = 0.0
                line.cumulative_percent = 0.0

    def _inverse_cumulative_percent(self):
        for line in self:
            line.cumulative_certified_qty = (line.budget_qty or 0.0) * (line.cumulative_percent or 0.0) / 100.0

    @api.depends("previous_certified_qty", "current_certified_qty", "cumulative_certified_qty", "price_unit")
    def _compute_amounts(self):
        for line in self:
            line.previous_amount = (line.previous_certified_qty or 0.0) * (line.price_unit or 0.0)
            line.current_amount = (line.current_certified_qty or 0.0) * (line.price_unit or 0.0)
            line.cumulative_amount = (line.cumulative_certified_qty or 0.0) * (line.price_unit or 0.0)

    def _prepare_invoice_line_vals(self):
        """Compatibility method kept for customizations using old per-line billing."""
        self.ensure_one()
        sale_line = self.sale_order_line_id
        product = sale_line.product_id if sale_line else self.env.ref("tl_bc3_sale.product_bc3_work_unit", raise_if_not_found=False)
        account = self._get_income_account(product)
        if not account:
            raise UserError(_("No se ha encontrado cuenta de ingresos para la línea de certificación BC3 %s.") % self.bc3_code)
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
