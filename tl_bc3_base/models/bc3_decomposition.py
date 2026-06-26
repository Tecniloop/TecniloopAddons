from odoo import api, fields, models


class Bc3DecompositionLine(models.Model):
    _name = "bc3.decomposition.line"
    _description = "BC3 Decomposition Line"
    _order = "file_id, parent_code, sequence, id"

    file_id = fields.Many2one("bc3.file", required=True, ondelete="cascade", index=True)
    parent_code = fields.Char(required=True, index=True)
    child_code = fields.Char(required=True, index=True)
    parent_concept_id = fields.Many2one("bc3.concept", index=True)
    child_concept_id = fields.Many2one("bc3.concept", index=True)
    sequence = fields.Integer(default=10)
    factor = fields.Float(default=1.0, digits="Product Unit of Measure")
    performance = fields.Float(default=1.0, digits="Product Unit of Measure")
    quantity = fields.Float(compute="_compute_quantity", store=True, digits="Product Unit of Measure")
    percent_codes = fields.Char()

    @api.depends("factor", "performance")
    def _compute_quantity(self):
        for line in self:
            line.quantity = (line.factor or 1.0) * (line.performance or 1.0)
