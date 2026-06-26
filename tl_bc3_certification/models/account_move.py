from odoo import fields, models


class AccountMove(models.Model):
    _inherit = "account.move"

    bc3_certification_id = fields.Many2one("bc3.certification", string="BC3 Certification", copy=False, index=True)


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    bc3_certification_line_id = fields.Many2one("bc3.certification.line", string="BC3 Certification Line", copy=False, index=True)
    bc3_budget_line_id = fields.Many2one("bc3.budget.line", string="BC3 Budget Line", copy=False, index=True)
    bc3_code = fields.Char(copy=False, index=True)
    bc3_cumulative_qty = fields.Float(string="BC3 Cumulative Qty", copy=False, digits="Product Unit of Measure")
