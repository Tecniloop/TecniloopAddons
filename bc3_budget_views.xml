from odoo import _, fields, models
from odoo.exceptions import UserError


class Bc3File(models.Model):
    _inherit = "bc3.file"

    def action_create_budget(self):
        self.ensure_one()
        if self.state != "parsed":
            raise UserError(_("Procese el fichero BC3 antes de crear un presupuesto."))
        budget = self.env["bc3.budget"].create_from_file(self)
        return {
            "type": "ir.actions.act_window",
            "name": _("Presupuesto BC3"),
            "res_model": "bc3.budget",
            "view_mode": "form",
            "res_id": budget.id,
        }

class Bc3FileBudgetLinks(models.Model):
    _inherit = "bc3.file"

    budget_ids = fields.One2many("bc3.budget", "file_id", string="Presupuestos")
    budget_count = fields.Integer(string="Presupuestos", compute="_compute_budget_count")

    def _compute_budget_count(self):
        for rec in self:
            rec.budget_count = len(rec.budget_ids)

    def action_open_budgets(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Presupuestos BC3"),
            "res_model": "bc3.budget",
            "view_mode": "list,form",
            "domain": [("file_id", "=", self.id)],
            "context": {"default_file_id": self.id},
        }
