from odoo import _, fields, models


class AccountMove(models.Model):
    _inherit = "account.move"

    bc3_certification_id = fields.Many2one("bc3.certification", string="Certificación BC3", copy=False, index=True)
    bc3_sale_order_id = fields.Many2one(
        "sale.order",
        string="Pedido de venta BC3",
        related="bc3_certification_id.sale_order_id",
        store=True,
        readonly=True,
    )

    def action_open_bc3_certification(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Certificación BC3"),
            "res_model": "bc3.certification",
            "view_mode": "form",
            "res_id": self.bc3_certification_id.id,
        }

    def _bc3_certifications_to_sync(self):
        return self.mapped("bc3_certification_id").exists()

    def unlink(self):
        certifications = self._bc3_certifications_to_sync()
        res = super().unlink()
        certifications._sync_invoice_state_from_invoices()
        return res

    def button_cancel(self):
        certifications = self._bc3_certifications_to_sync()
        res = super().button_cancel()
        certifications._sync_invoice_state_from_invoices()
        return res

    def write(self, vals):
        certifications = self._bc3_certifications_to_sync()
        res = super().write(vals)
        if "state" in vals or "bc3_certification_id" in vals:
            certifications |= self._bc3_certifications_to_sync()
            certifications._sync_invoice_state_from_invoices()
        return res


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    bc3_certification_line_id = fields.Many2one("bc3.certification.line", string="Línea de certificación BC3", copy=False, index=True)
    bc3_budget_line_id = fields.Many2one("bc3.budget.line", string="Línea de presupuesto BC3", copy=False, index=True)
    bc3_code = fields.Char(string="Código BC3", copy=False, index=True)
    bc3_cumulative_qty = fields.Float(string="Cantidad acumulada BC3", copy=False, digits="Product Unit of Measure")
