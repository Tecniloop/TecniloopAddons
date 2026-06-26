from odoo import _, fields, models


class SaleOrder(models.Model):
    _inherit = "sale.order"

    bc3_certification_ids = fields.One2many(
        "bc3.certification",
        "sale_order_id",
        string="Certificaciones BC3",
        copy=False,
    )
    bc3_certification_count = fields.Integer(compute="_compute_bc3_certification_count")

    def _compute_bc3_certification_count(self):
        grouped = self.env["bc3.certification"].read_group(
            [("sale_order_id", "in", self.ids)],
            ["sale_order_id"],
            ["sale_order_id"],
        )
        counts = {row["sale_order_id"][0]: row["sale_order_id_count"] for row in grouped if row.get("sale_order_id")}
        for order in self:
            order.bc3_certification_count = counts.get(order.id, 0)

    def action_create_bc3_certification(self):
        self.ensure_one()
        cert = self.env["bc3.certification"].create_from_sale_order(self)
        return {
            "type": "ir.actions.act_window",
            "name": _("Certificación BC3"),
            "res_model": "bc3.certification",
            "view_mode": "form",
            "res_id": cert.id,
            "context": {"default_sale_order_id": self.id, "default_budget_id": self.bc3_budget_id.id},
        }

    def action_open_bc3_certifications(self):
        self.ensure_one()
        action = {
            "type": "ir.actions.act_window",
            "name": _("Certificaciones BC3"),
            "res_model": "bc3.certification",
            "view_mode": "list,form",
            "domain": [("sale_order_id", "=", self.id)],
            "context": {"default_sale_order_id": self.id, "default_budget_id": self.bc3_budget_id.id},
        }
        if self.bc3_certification_count == 1:
            certification = self.bc3_certification_ids[:1]
            action.update({"view_mode": "form", "res_id": certification.id})
        return action
