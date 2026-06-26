from odoo import _, fields, models
from odoo.exceptions import UserError


class Bc3Budget(models.Model):
    _inherit = "bc3.budget"

    sale_order_ids = fields.One2many("sale.order", "bc3_budget_id", string="Presupuestos de venta")
    sale_order_count = fields.Integer(string="Presupuestos de venta", compute="_compute_sale_order_count")

    def _compute_sale_order_count(self):
        for budget in self:
            budget.sale_order_count = len(budget.sale_order_ids)

    def action_create_sale_order(self):
        self.ensure_one()
        if not self.line_ids:
            raise UserError(_("El presupuesto BC3 no tiene líneas."))
        partner_id = self.env.context.get("default_partner_id")
        if not partner_id:
            partner_id = self.env.user.company_id.partner_id.id
        order = self.env["sale.order"].create({
            "partner_id": partner_id,
            "bc3_budget_id": self.id,
            "origin": self.name,
        })
        order.action_fill_from_bc3_budget()
        return {
            "type": "ir.actions.act_window",
            "name": _("Presupuesto de venta"),
            "res_model": "sale.order",
            "view_mode": "form",
            "res_id": order.id,
        }

    def action_open_sale_orders(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Presupuestos de venta"),
            "res_model": "sale.order",
            "view_mode": "list,form",
            "domain": [("bc3_budget_id", "=", self.id)],
            "context": {"default_bc3_budget_id": self.id},
        }
