from odoo import _, fields, models
from odoo.exceptions import UserError


class Bc3ImportWizard(models.TransientModel):
    _name = "bc3.import.wizard"
    _description = "BC3 Import Wizard"

    name = fields.Char(default=lambda self: _("BC3 import"), required=True)
    data_file = fields.Binary(string="BC3 File", required=True, attachment=True)
    filename = fields.Char(required=True)
    parse_now = fields.Boolean(default=True)

    def action_import(self):
        self.ensure_one()
        if not self.data_file:
            raise UserError(_("Please upload a BC3 file."))
        bc3_file = self.env["bc3.file"].create({
            "name": self.filename or self.name,
            "filename": self.filename,
            "data_file": self.data_file,
        })
        if self.parse_now:
            bc3_file.action_parse()
        return {
            "type": "ir.actions.act_window",
            "name": _("BC3 File"),
            "res_model": "bc3.file",
            "view_mode": "form",
            "res_id": bc3_file.id,
        }
