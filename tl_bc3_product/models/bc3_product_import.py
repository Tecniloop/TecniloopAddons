from odoo import fields, models


class Bc3ProductImportBatch(models.Model):
    _name = "bc3.product.import.batch"
    _description = "BC3 Product Import Batch"
    _order = "id desc"

    name = fields.Char(required=True)
    file_id = fields.Many2one("bc3.file", index=True)
    brand_id = fields.Many2one("res.brand", string="Brand")
    state = fields.Selection(
        [("draft", "Draft"), ("running", "Running"), ("done", "Done"), ("error", "Error")],
        default="draft",
        required=True,
    )
    started_at = fields.Datetime(default=fields.Datetime.now)
    finished_at = fields.Datetime()
    total_concepts = fields.Integer()
    created_products = fields.Integer()
    updated_products = fields.Integer()
    skipped_products = fields.Integer()
    media_created = fields.Integer()
    warning_count = fields.Integer()
    error_count = fields.Integer()
    log_ids = fields.One2many("bc3.product.import.log", "batch_id", string="Logs")


class Bc3ProductImportLog(models.Model):
    _name = "bc3.product.import.log"
    _description = "BC3 Product Import Log"
    _order = "batch_id desc, id desc"

    batch_id = fields.Many2one("bc3.product.import.batch", required=True, ondelete="cascade", index=True)
    level = fields.Selection([("info", "Info"), ("warning", "Warning"), ("error", "Error")], default="info", required=True)
    bc3_code = fields.Char(index=True)
    message = fields.Text(required=True)
