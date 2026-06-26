from odoo import _, models


class Bc3File(models.Model):
    _inherit = "bc3.file"

    def action_open_product_import_wizard(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Import BC3 Products"),
            "res_model": "bc3.product.import.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_file_id": self.id, "default_brand_name": self.property_file or self.name},
        }
