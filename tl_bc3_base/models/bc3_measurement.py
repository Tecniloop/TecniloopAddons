from odoo import fields, models


class Bc3MeasurementLine(models.Model):
    _name = "bc3.measurement.line"
    _description = "BC3 Measurement Line"
    _order = "file_id, parent_code, child_code, position_path, sequence, id"

    file_id = fields.Many2one("bc3.file", required=True, ondelete="cascade", index=True)
    parent_code = fields.Char(index=True)
    child_code = fields.Char(required=True, index=True)
    parent_concept_id = fields.Many2one("bc3.concept", index=True)
    child_concept_id = fields.Many2one("bc3.concept", index=True)
    position_path = fields.Char(index=True)
    measurement_total = fields.Float(digits="Product Unit of Measure")
    sequence = fields.Integer(default=10)
    line_type = fields.Selection(
        [("", "Normal"), ("1", "Partial subtotal"), ("2", "Accumulated subtotal"), ("3", "Expression")],
        default="",
    )
    comment = fields.Char()
    bim_id = fields.Char(string="BIM ID")
    units = fields.Float(digits="Product Unit of Measure")
    length = fields.Float(digits="Product Unit of Measure")
    width = fields.Float(digits="Product Unit of Measure")
    height = fields.Float(digits="Product Unit of Measure")
    subtotal = fields.Float(digits="Product Unit of Measure")
    label = fields.Char()
