from odoo import _, fields, models
from odoo.exceptions import UserError


class Bc3Concept(models.Model):
    _inherit = "bc3.concept"

    product_tmpl_id = fields.Many2one("product.template", string="Product", copy=False, readonly=True)
    product_count = fields.Integer(compute="_compute_product_count")

    def _compute_product_count(self):
        for concept in self:
            concept.product_count = 1 if concept.product_tmpl_id else 0

    def action_create_or_update_product(self):
        self.ensure_one()
        if self.category in ("root", "chapter", "percentage"):
            raise UserError(_("Root, chapter and percentage concepts are not imported as products."))
        wizard = self.env["bc3.product.import.wizard"].create({
            "file_id": self.file_id.id,
            "update_existing": True,
            "import_work_units": self.category == "work_unit",
            "import_resources": self.category == "resource",
            "import_other": self.category == "other",
            "include_zero_price": True,
            "brand_name": self.file_id.property_file or self.file_id.name,
        })
        product, _created = wizard._create_or_update_product(self, wizard._get_or_create_brand())
        return {
            "type": "ir.actions.act_window",
            "name": _("Product"),
            "res_model": "product.template",
            "view_mode": "form",
            "res_id": product.id,
        }

    def action_open_product(self):
        self.ensure_one()
        if not self.product_tmpl_id:
            return False
        return {
            "type": "ir.actions.act_window",
            "name": _("Product"),
            "res_model": "product.template",
            "view_mode": "form",
            "res_id": self.product_tmpl_id.id,
        }
