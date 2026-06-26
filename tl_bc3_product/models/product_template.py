from odoo import fields, models


class ProductTemplate(models.Model):
    _inherit = ["product.template", "res.brand.mixin"]

    bc3_is_imported = fields.Boolean(string="Imported from BC3", copy=False, index=True)
    bc3_file_id = fields.Many2one("bc3.file", string="BC3 File", copy=False, index=True)
    bc3_concept_id = fields.Many2one("bc3.concept", string="BC3 Concept", copy=False, index=True)
    bc3_code = fields.Char(string="BC3 Code", copy=False, index=True)
    bc3_normalized_code = fields.Char(string="BC3 Normalized Code", copy=False, index=True)
    bc3_alias_codes = fields.Char(string="BC3 Alias Codes", copy=False)
    bc3_category = fields.Selection(
        [
            ("root", "Root"),
            ("chapter", "Chapter"),
            ("work_unit", "Work Unit"),
            ("resource", "Resource"),
            ("percentage", "Percentage"),
            ("other", "Other"),
        ],
        string="BC3 Category",
        copy=False,
        index=True,
    )
    bc3_type = fields.Char(string="BC3 Type", copy=False)
    bc3_unit_name = fields.Char(string="BC3 Unit", copy=False)
    bc3_price_date_raw = fields.Char(string="BC3 Price Date", copy=False)
    bc3_text = fields.Text(string="BC3 Text", copy=False)
    bc3_technical_json = fields.Text(string="BC3 Technical Data", copy=False)
    bc3_media_refs = fields.Text(string="BC3 Media References", copy=False)
    bc3_last_import_date = fields.Datetime(string="Last BC3 Import", copy=False, readonly=True)

    def action_open_bc3_concept(self):
        self.ensure_one()
        if not self.bc3_concept_id:
            return False
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("BC3 Concept"),
            "res_model": "bc3.concept",
            "view_mode": "form",
            "res_id": self.bc3_concept_id.id,
        }
