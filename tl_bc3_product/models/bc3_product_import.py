from odoo import _, api, fields, models
from odoo.exceptions import UserError


class Bc3ProductImportBatch(models.Model):
    _name = "bc3.product.import.batch"
    _description = "BC3 Product Import Batch"
    _order = "id desc"

    name = fields.Char(required=True)
    file_id = fields.Many2one("bc3.file", index=True, required=True)
    manufacturer_id = fields.Many2one("bc3.product.manufacturer", string="Manufacturer", index=True)
    brand_id = fields.Many2one("res.brand", string="Brand")
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("queued", "Queued"),
            ("running", "Running"),
            ("partial", "Partial"),
            ("done", "Done"),
            ("error", "Error"),
        ],
        default="draft",
        required=True,
    )
    started_at = fields.Datetime()
    finished_at = fields.Datetime()
    batch_size = fields.Integer(default=200, required=True)
    total_concepts = fields.Integer()
    processed_concepts = fields.Integer()
    pending_concepts = fields.Integer(compute="_compute_pending_concepts")
    created_products = fields.Integer()
    updated_products = fields.Integer()
    skipped_products = fields.Integer()
    media_created = fields.Integer()
    warning_count = fields.Integer()
    error_count = fields.Integer()
    line_ids = fields.One2many("bc3.product.import.line", "batch_id", string="Lines")
    log_ids = fields.One2many("bc3.product.import.log", "batch_id", string="Logs")

    create_website_categories = fields.Boolean(default=True)
    website_parent_categ_id = fields.Many2one("product.public.category", string="Parent Website Category")
    replace_website_categories = fields.Boolean(string="Replace Existing Website Categories")
    include_zero_price = fields.Boolean(default=True)
    update_existing = fields.Boolean(default=True)
    publish_on_website = fields.Boolean()
    default_product_type = fields.Selection([("consu", "Goods"), ("service", "Service")], default="consu", required=True)
    track_inventory = fields.Boolean(default=True)
    import_images = fields.Boolean(default=True)
    set_first_image = fields.Boolean(default=True)
    overwrite_image = fields.Boolean()
    media_zip_file = fields.Binary(string="Media ZIP", attachment=True)
    media_zip_filename = fields.Char()
    media_server_path = fields.Char(string="Media Server Path")
    max_related_file_size_mb = fields.Integer(default=75)

    def _compute_pending_concepts(self):
        Line = self.env["bc3.product.import.line"].sudo()
        for batch in self:
            batch.pending_concepts = Line.search_count([("batch_id", "=", batch.id), ("state", "=", "pending")])

    def action_process_next_chunk(self):
        self.ensure_one()
        self._process_next_chunk(limit=self.batch_size or 200)
        return self._open_self()

    def action_process_ten_chunks(self):
        self.ensure_one()
        for _i in range(10):
            self.invalidate_recordset()
            if self.state not in ("queued", "partial", "running"):
                break
            self._process_next_chunk(limit=self.batch_size or 200)
        return self._open_self()

    def _open_self(self):
        return {
            "type": "ir.actions.act_window",
            "name": _("BC3 Product Import"),
            "res_model": "bc3.product.import.batch",
            "view_mode": "form",
            "res_id": self.id,
        }

    def _process_next_chunk(self, limit=None):
        self.ensure_one()
        limit = max(int(limit or self.batch_size or 200), 1)
        lines = self.env["bc3.product.import.line"].sudo().search(
            [("batch_id", "=", self.id), ("state", "=", "pending")],
            order="sequence,id",
            limit=limit,
        )
        if not lines:
            self.write({"state": "error" if self.error_count else "done", "finished_at": fields.Datetime.now()})
            return self
        self.write({"state": "running", "started_at": self.started_at or fields.Datetime.now()})
        wizard = self._make_runtime_wizard()
        media_reader = wizard._make_media_reader(self)
        counters = {
            "created_products": self.created_products,
            "updated_products": self.updated_products,
            "skipped_products": self.skipped_products,
            "media_created": self.media_created,
            "warning_count": self.warning_count,
            "error_count": self.error_count,
            "processed_concepts": self.processed_concepts,
        }
        for line in lines:
            try:
                with self.env.cr.savepoint():
                    product, created = wizard._create_or_update_product(line.concept_id, self.brand_id)
                    if not product:
                        counters["skipped_products"] += 1
                        line.write({"state": "skipped", "message": _("Product exists and update is disabled.")})
                    else:
                        if created:
                            counters["created_products"] += 1
                        else:
                            counters["updated_products"] += 1
                        media_created, warnings = wizard._import_ecommerce_media_with_reader(product, line.concept_id, media_reader)
                        counters["media_created"] += media_created
                        counters["warning_count"] += warnings
                        line.write({"state": "done", "product_id": product.id, "media_created": media_created, "message": _("Imported")})
            except Exception as exc:
                counters["error_count"] += 1
                line.write({"state": "error", "message": str(exc)})
                self._log("error", line.concept_id.code, str(exc))
            counters["processed_concepts"] += 1
        remaining = self.env["bc3.product.import.line"].sudo().search_count([("batch_id", "=", self.id), ("state", "=", "pending")])
        vals = dict(counters)
        if remaining:
            vals["state"] = "partial"
        else:
            vals["state"] = "error" if counters["error_count"] else "done"
            vals["finished_at"] = fields.Datetime.now()
        self.write(vals)
        self.env.cr.commit()
        return self

    def _make_runtime_wizard(self):
        vals = {
            "file_id": self.file_id.id,
            "brand_id": self.brand_id.id if self.brand_id else False,
            "create_website_categories": self.create_website_categories,
            "website_parent_categ_id": self.website_parent_categ_id.id if self.website_parent_categ_id else False,
            "replace_website_categories": self.replace_website_categories,
            "include_zero_price": self.include_zero_price,
            "update_existing": self.update_existing,
            "publish_on_website": self.publish_on_website,
            "default_product_type": self.default_product_type,
            "track_inventory": self.track_inventory,
            "import_images": self.import_images,
            "set_first_image": self.set_first_image,
            "overwrite_image": self.overwrite_image,
            "media_zip_file": self.media_zip_file,
            "media_zip_filename": self.media_zip_filename,
            "media_server_path": self.media_server_path,
            "max_related_file_size_mb": self.max_related_file_size_mb,
        }
        return self.env["bc3.product.import.wizard"].sudo().create(vals)

    def _log(self, level, code, message):
        self.env["bc3.product.import.log"].sudo().create({
            "batch_id": self.id,
            "level": level,
            "bc3_code": code,
            "message": message,
        })

    @api.model
    def _cron_process_pending_batches(self):
        batches = self.sudo().search([("state", "in", ("queued", "partial"))], order="id", limit=3)
        for batch in batches:
            try:
                batch._process_next_chunk(limit=batch.batch_size or 200)
            except Exception as exc:
                batch._log("error", "", _("Batch processor failed: %s") % exc)
                batch.write({"state": "error", "error_count": batch.error_count + 1, "finished_at": fields.Datetime.now()})
            self.env.cr.commit()


class Bc3ProductImportLine(models.Model):
    _name = "bc3.product.import.line"
    _description = "BC3 Product Import Line"
    _order = "batch_id, sequence, id"

    batch_id = fields.Many2one("bc3.product.import.batch", required=True, ondelete="cascade", index=True)
    sequence = fields.Integer(default=10, index=True)
    concept_id = fields.Many2one("bc3.concept", required=True, ondelete="cascade", index=True)
    code = fields.Char(related="concept_id.code", store=True, index=True)
    name = fields.Char(related="concept_id.name", store=True)
    state = fields.Selection(
        [("pending", "Pending"), ("done", "Done"), ("skipped", "Skipped"), ("error", "Error")],
        default="pending",
        required=True,
        index=True,
    )
    product_id = fields.Many2one("product.template", string="Product")
    media_created = fields.Integer()
    message = fields.Text()


class Bc3ProductImportLog(models.Model):
    _name = "bc3.product.import.log"
    _description = "BC3 Product Import Log"
    _order = "batch_id desc, id desc"

    batch_id = fields.Many2one("bc3.product.import.batch", required=True, ondelete="cascade", index=True)
    level = fields.Selection([("info", "Info"), ("warning", "Warning"), ("error", "Error")], default="info", required=True)
    bc3_code = fields.Char(index=True)
    message = fields.Text(required=True)
