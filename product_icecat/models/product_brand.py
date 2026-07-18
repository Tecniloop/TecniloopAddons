# Copyright 2026 Custom Development
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
import logging

from odoo import api, fields, models
from odoo.exceptions import UserError

from .icecat_api import IcecatError, get_client_from_env

_logger = logging.getLogger(__name__)

# How many pending lines the cron processes per tick, across all brands
# currently importing. Keep this modest: each line is one Icecat XML fetch
# plus up to N image downloads, all synchronous HTTP calls.
BULK_IMPORT_BATCH_SIZE = 20


class ProductBrand(models.Model):
    _inherit = "product.brand"

    icecat_manufacturer_id = fields.Many2one(
        comodel_name="icecat.manufacturer",
        help="Icecat manufacturer linked to this brand. Used to look up "
        "products by part number on the Icecat catalog, and to resolve "
        "the default import settings (images, categories) applied when "
        "importing products for this brand.",
    )

    # -- bulk "import all products" ---------------------------------------
    icecat_bulk_state = fields.Selection(
        [
            ("none", "Not Started"),
            ("scanning", "Scanning Catalog..."),
            ("importing", "Importing Products..."),
            ("done", "Done"),
            ("error", "Error"),
        ],
        default="none",
        copy=False,
        help="Status of the last 'Import All Products from Icecat' run for "
        "this brand.",
    )
    icecat_bulk_error_message = fields.Text(copy=False)
    icecat_bulk_index_type = fields.Selection(
        [
            ("on_market", "On-Market Products"),
            ("full", "Full Catalog"),
            ("daily", "Daily Changes"),
        ],
        string="Catalog Index",
        default="on_market",
        required=True,
        help="On-Market Products is the recommended option: it scans only "
        "products that Icecat has identified as distributed in the market "
        "associated with the configured Icecat data language. "
        "Full Catalog scans every available product and is much larger. "
        "Daily Changes only contains products updated during the previous "
        "day.",
    )
    icecat_bulk_modified_since = fields.Date(
        string="Modified Since",
        help="Only queue index entries whose Icecat Updated timestamp is on "
        "or after this date. Leave empty to include all dates available in "
        "the selected index.",
    )
    icecat_bulk_added_since = fields.Date(
        string="Added Since",
        help="Only queue products whose Icecat Date_Added timestamp is on or "
        "after this date. Unlike Modified Since, this excludes old products "
        "that were merely edited recently.",
    )
    icecat_bulk_category_ids = fields.Many2many(
        comodel_name="icecat.category",
        relation="product_brand_icecat_bulk_category_rel",
        column1="product_brand_id",
        column2="icecat_category_id",
        string="Icecat Categories",
        help="Only import products assigned to these Icecat categories. "
        "Leave empty to allow every category for this brand.",
    )
    icecat_bulk_include_child_categories = fields.Boolean(
        string="Include Child Categories",
        default=True,
        help="When categories are selected, also accept every descendant "
        "category in the Icecat taxonomy.",
    )
    icecat_bulk_quality = fields.Selection(
        [
            ("described", "Icecat or Supplier Described"),
            ("icecat", "Icecat Standardized Only"),
            ("supplier", "Supplier Data Only"),
        ],
        string="Data Quality",
        default="described",
        required=True,
        help="ICECAT records are standardized and reviewed by Icecat. "
        "SUPPLIER records are imported directly from the manufacturer's "
        "source and may not yet be standardized. Removed and undescribed "
        "records are never queued.",
    )
    icecat_bulk_only_on_market = fields.Boolean(
        string="Only On-Market Products",
        default=True,
        help="Require the index entry to be marked as currently on market. "
        "This is redundant for the On-Market index, but useful with Full "
        "Catalog and Daily Changes.",
    )
    icecat_bulk_only_with_image = fields.Boolean(
        string="Only Products with Main Image",
        default=False,
        help="Skip index entries that do not expose a HighPic main image.",
    )
    icecat_bulk_only_unrestricted = fields.Boolean(
        string="Exclude Restricted Products",
        default=True,
        help="Skip entries marked as Limited by Icecat, which normally "
        "require brand authorization and would otherwise fail during import.",
    )
    icecat_bulk_limit = fields.Integer(
        string="Max Products to Import",
        default=0,
        help="Stop queuing new products once this many matches have been "
        "found in a single scan. 0 means no limit.",
    )
    icecat_bulk_total = fields.Integer(readonly=True, copy=False)
    icecat_import_line_ids = fields.One2many(
        comodel_name="icecat.import.line", inverse_name="product_brand_id"
    )
    icecat_bulk_pending_count = fields.Integer(compute="_compute_icecat_bulk_counts")
    icecat_bulk_done_count = fields.Integer(compute="_compute_icecat_bulk_counts")
    icecat_bulk_error_count = fields.Integer(compute="_compute_icecat_bulk_counts")
    icecat_bulk_skipped_count = fields.Integer(compute="_compute_icecat_bulk_counts")

    @api.depends("icecat_import_line_ids.state")
    def _compute_icecat_bulk_counts(self):
        for brand in self:
            lines = brand.icecat_import_line_ids
            brand.icecat_bulk_pending_count = len(lines.filtered(lambda l: l.state == "pending"))
            brand.icecat_bulk_done_count = len(lines.filtered(lambda l: l.state == "done"))
            brand.icecat_bulk_error_count = len(lines.filtered(lambda l: l.state == "error"))
            brand.icecat_bulk_skipped_count = len(lines.filtered(lambda l: l.state == "skipped"))

    # ------------------------------------------------------------------
    def action_icecat_bulk_import_start(self):
        """Kick off (or resume) a bulk import of all of this brand's
        products from Icecat. Runs entirely in the background: this just
        flags the brand and nudges the cron to pick it up right away.
        """
        self.ensure_one()
        if not self.icecat_manufacturer_id:
            raise UserError(
                self.env._("Link this brand to an Icecat manufacturer on its Icecat tab first.")
            )
        if not self.icecat_manufacturer_id.icecat_supplier_id:
            # No Supplier ID yet: resolve it automatically from Icecat's
            # suppliers list instead of asking the user for it.
            try:
                unmatched = self.icecat_manufacturer_id._icecat_resolve_supplier_ids()
            except IcecatError as exc:
                raise UserError(str(exc)) from exc
            if unmatched:
                raise UserError(
                    self.env._(
                        "Icecat's suppliers list has no supplier named "
                        "%(manufacturer)s, so its Supplier ID could not be "
                        "determined automatically. Check the manufacturer's "
                        "name against Icecat's spelling (run 'Sync "
                        "Manufacturers from Icecat' to browse the list), or "
                        "fill in its Supplier ID by hand.",
                        manufacturer=self.icecat_manufacturer_id.name,
                    )
                )
        self.write(
            {
                "icecat_bulk_state": "scanning",
                "icecat_bulk_error_message": False,
                "icecat_bulk_total": 0,
            }
        )
        self._icecat_trigger_bulk_cron()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": self.env._("Import queued"),
                "message": self.env._(
                    "Scanning the selected Icecat index for %(brand)s's "
                    "products in the background. Brand, categories, dates, "
                    "quality and availability filters are applied before "
                    "products are queued — check the Icecat tab for progress.",
                    brand=self.name,
                ),
                "type": "success",
                "sticky": False,
            },
        }

    def action_icecat_bulk_import_reset(self):
        self.ensure_one()
        self.icecat_import_line_ids.unlink()
        self.write(
            {
                "icecat_bulk_state": "none",
                "icecat_bulk_error_message": False,
                "icecat_bulk_total": 0,
            }
        )

    def action_icecat_bulk_retry_errors(self):
        self.ensure_one()
        errored = self.icecat_import_line_ids.filtered(lambda l: l.state == "error")
        if not errored:
            return True
        errored.write({"state": "pending", "error_message": False})
        if self.icecat_bulk_state in ("done", "error"):
            self.icecat_bulk_state = "importing"
        self._icecat_trigger_bulk_cron()
        return True

    def action_view_icecat_import_lines(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Icecat Import Lines"),
            "res_model": "icecat.import.line",
            "view_mode": "list,form",
            "domain": [("product_brand_id", "=", self.id)],
        }

    def _icecat_trigger_bulk_cron(self):
        cron = self.env.ref("product_icecat.ir_cron_icecat_bulk_import", raise_if_not_found=False)
        if cron:
            cron.sudo()._trigger()

    # ------------------------------------------------------------------
    # scan: populate icecat.import.line from the Icecat catalog index
    # ------------------------------------------------------------------
    def _icecat_bulk_scan(self):
        self.ensure_one()
        manufacturer = self.icecat_manufacturer_id
        client = get_client_from_env(self.env)

        import_line_model = self.env["icecat.import.line"].sudo()
        already_queued = set(
            import_line_model.search([("product_brand_id", "=", self.id)]).mapped("part_number")
        )
        existing_products = set(
            self.env["product.template"]
            .sudo()
            .search([("product_brand_id", "=", self.id), ("icecat_prod_id", "!=", False)])
            .mapped("icecat_prod_id")
        )
        existing_products.update(
            self.env["product.template"]
            .sudo()
            .search([("product_brand_id", "=", self.id), ("default_code", "!=", False)])
            .mapped("default_code")
        )

        category_ids = set(self.icecat_bulk_category_ids.mapped("icecat_id"))
        if category_ids and self.icecat_bulk_include_child_categories:
            category_ids = set(
                self.env["icecat.category"]
                .sudo()
                .search([("id", "child_of", self.icecat_bulk_category_ids.ids)])
                .mapped("icecat_id")
            )

        count = 0
        create_vals = []
        for part_number in client.iter_catalog_index_by_supplier(
            manufacturer.icecat_supplier_id,
            index_type=self.icecat_bulk_index_type,
            modified_since=self.icecat_bulk_modified_since,
            added_since=self.icecat_bulk_added_since,
            category_ids=category_ids,
            quality_mode=self.icecat_bulk_quality,
            only_on_market=self.icecat_bulk_only_on_market,
            only_with_image=self.icecat_bulk_only_with_image,
            only_unrestricted=self.icecat_bulk_only_unrestricted,
        ):
            if part_number in already_queued:
                continue
            already_queued.add(part_number)
            state = "skipped" if part_number in existing_products else "pending"
            create_vals.append(
                {
                    "product_brand_id": self.id,
                    "icecat_manufacturer_id": manufacturer.id,
                    "part_number": part_number,
                    "state": state,
                }
            )
            count += 1
            if create_vals and len(create_vals) >= 500:
                import_line_model.create(create_vals)
                create_vals = []
            if self.icecat_bulk_limit and count >= self.icecat_bulk_limit:
                break
        if create_vals:
            import_line_model.create(create_vals)

        self.write({"icecat_bulk_state": "importing", "icecat_bulk_total": count})

    # ------------------------------------------------------------------
    # cron entrypoint
    #
    # This method commits the transaction explicitly and repeatedly
    # (flagged by pylint-odoo's invalid-commit check, disabled below with
    # a reason on each occurrence). This is the same pattern OCA's own
    # `queue_job` module uses in its cron-driven cleanup loop
    # (queue_job/models/queue_job.py): a background cron processing many
    # independent external HTTP calls over several minutes needs partial
    # progress to survive a worker restart or a mid-batch failure, which a
    # single end-of-request commit cannot provide.
    # ------------------------------------------------------------------
    @api.model
    def _cron_process_icecat_bulk_import(self):
        scanning_brands = self.search([("icecat_bulk_state", "=", "scanning")])
        for brand in scanning_brands:
            try:
                brand._icecat_bulk_scan()
                self.env.cr.commit()  # pylint: disable=invalid-commit
            except IcecatError as exc:
                brand.write({"icecat_bulk_state": "error", "icecat_bulk_error_message": str(exc)})
                self.env.cr.commit()  # pylint: disable=invalid-commit
            except Exception as exc:  # pylint: disable=broad-exception-caught
                # Deliberately broad: one brand's scan failing for any
                # unexpected reason must not stop the cron from handling
                # the other brands queued alongside it.
                _logger.exception(
                    "Icecat bulk import: scan failed for brand %s", brand.display_name
                )
                brand.write({"icecat_bulk_state": "error", "icecat_bulk_error_message": str(exc)})
                self.env.cr.commit()  # pylint: disable=invalid-commit

        pending_lines = self.env["icecat.import.line"].search(
            [
                ("state", "=", "pending"),
                ("product_brand_id.icecat_bulk_state", "=", "importing"),
            ],
            limit=BULK_IMPORT_BATCH_SIZE,
        )
        touched_brands = pending_lines.product_brand_id
        for line in pending_lines:
            line._process()
            self.env.cr.commit()  # pylint: disable=invalid-commit

        for brand in touched_brands:
            if not brand.icecat_import_line_ids.filtered(lambda l: l.state == "pending"):
                brand.icecat_bulk_state = "done"
                self.env.cr.commit()  # pylint: disable=invalid-commit

        # also close out brands that reached 'importing' with nothing to do
        # (e.g. every match was already imported and marked 'skipped')
        stalled_brands = self.search([("icecat_bulk_state", "=", "importing")])
        for brand in stalled_brands:
            if not brand.icecat_import_line_ids.filtered(lambda l: l.state == "pending"):
                brand.icecat_bulk_state = "done"
                self.env.cr.commit()  # pylint: disable=invalid-commit
