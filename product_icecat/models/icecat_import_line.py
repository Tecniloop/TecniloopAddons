# Copyright 2026 Custom Development
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
import logging

from odoo import fields, models
from odoo.exceptions import UserError

from .icecat_api import IcecatError, get_client_from_env

_logger = logging.getLogger(__name__)


class IcecatImportLine(models.Model):
    _name = "icecat.import.line"
    _description = "Icecat Bulk Import Line"
    _order = "id"
    _rec_name = "part_number"

    product_brand_id = fields.Many2one(
        comodel_name="product.brand",
        string="Brand",
        required=True,
        index=True,
        ondelete="cascade",
    )
    icecat_manufacturer_id = fields.Many2one(
        comodel_name="icecat.manufacturer",
        required=True,
        index=True,
        ondelete="cascade",
    )
    part_number = fields.Char(required=True, index=True)
    state = fields.Selection(
        [
            ("pending", "Pending"),
            ("done", "Done"),
            ("error", "Error"),
            ("skipped", "Skipped (already imported)"),
        ],
        default="pending",
        required=True,
        index=True,
    )
    error_message = fields.Text()
    product_id = fields.Many2one(comodel_name="product.template", readonly=True)

    _sql_constraints = [
        (
            "brand_part_number_uniq",
            "unique(product_brand_id, part_number)",
            "This part number is already queued for this brand.",
        ),
    ]

    def _process(self):
        """Fetch and import this line's product. Never raises: failures are
        recorded on the line itself so one bad product can't abort a batch.
        """
        self.ensure_one()
        manufacturer = self.icecat_manufacturer_id
        try:
            client = get_client_from_env(self.env)
            icecat_product = client.get_product_by_part_number(
                self.part_number, manufacturer.name
            )
            product = self.env["product.template"].sudo()._icecat_create_product(
                name=icecat_product.title,
                part_number=self.part_number,
                ean=icecat_product.ean,
                product_brand=self.product_brand_id,
                icecat_id=icecat_product.icecat_id,
                description_html=icecat_product.build_description_html(),
                category_icecat_id=icecat_product.category_icecat_id,
                category_name=icecat_product.category_name,
                main_image_url=icecat_product.main_image_url,
                gallery_image_urls=icecat_product.gallery_image_urls,
                import_main_image=manufacturer.import_main_image,
                import_gallery_images=manufacturer.import_gallery_images,
                create_product_category=manufacturer.create_product_category,
                create_ecommerce_category=manufacturer.create_ecommerce_category,
            )
            self.write({"state": "done", "product_id": product.id, "error_message": False})
        except IcecatError as exc:
            self.write({"state": "error", "error_message": str(exc)})
        except Exception as exc:  # pylint: disable=broad-exception-caught
            # Deliberately broad: this runs from a background cron batch
            # (see product.brand._cron_process_icecat_bulk_import) where
            # one product's unexpected failure (bad data, ORM error...)
            # must be recorded on its own line and not abort the rest of
            # the batch.
            _logger.exception(
                "Icecat bulk import: unexpected error processing part number %s",
                self.part_number,
            )
            self.write({"state": "error", "error_message": str(exc)})

    def action_retry(self):
        errored = self.filtered(lambda line: line.state == "error")
        if not errored:
            raise UserError(self.env._("Only lines in Error state can be retried."))
        errored.write({"state": "pending", "error_message": False})
        brands = errored.product_brand_id
        for brand in brands:
            if brand.icecat_bulk_state in ("done", "error"):
                brand.icecat_bulk_state = "importing"
        brands._icecat_trigger_bulk_cron()
