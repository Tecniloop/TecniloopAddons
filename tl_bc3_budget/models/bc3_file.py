from odoo import _, models
from odoo.exceptions import UserError


class Bc3File(models.Model):
    _inherit = "bc3.file"

    def action_create_budget(self):
        self.ensure_one()
        if self.state != "parsed":
            raise UserError(_("Parse the BC3 file before creating a budget."))
        budget = self.env["bc3.budget"].create_from_file(self)
        return {
            "type": "ir.actions.act_window",
            "name": _("BC3 Budget"),
            "res_model": "bc3.budget",
            "view_mode": "form",
            "res_id": budget.id,
        }
