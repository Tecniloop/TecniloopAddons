from odoo import _, fields, models


class SaleOrder(models.Model):
    _inherit = "sale.order"

    bc3_certification_ids = fields.One2many("bc3.certification", "sale_order_id", string="BC3 Certifications")
    bc3_certification_count = fields.Integer(compute="_compute_bc3_certification_count")

    def _compute_bc3_certification_count(self):
        for order in self:
            order.bc3_certification_count = len(order.bc3_certification_ids)

    def action_create_bc3_certification(self):
        self.ensure_one()
        cert = self.env["bc3.certification"].create_from_sale_order(self)
        return {
            "type": "ir.actions.act_window",
            "name": _("BC3 Certification"),
            "res_model": "bc3.certification",
            "view_mode": "form",
            "res_id": cert.id,
        }

    def action_open_bc3_certifications(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("BC3 Certifications"),
            "res_model": "bc3.certification",
            "view_mode": "list,form",
            "domain": [("sale_order_id", "=", self.id)],
            "context": {"default_sale_order_id": self.id, "default_budget_id": self.bc3_budget_id.id},
        }
