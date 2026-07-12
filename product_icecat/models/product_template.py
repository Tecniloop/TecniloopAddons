# Copyright 2026 Custom Development
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
import base64
import logging

import requests

from odoo import api, fields, models
from odoo.exceptions import UserError

from .icecat_api import IcecatError, get_client_from_env

_logger = logging.getLogger(__name__)


class ProductTemplate(models.Model):
    _inherit = "product.template"

    icecat_category_id = fields.Many2one(
        comodel_name="icecat.category",
        help="Icecat catalog category this product was classified under.",
        copy=False,
    )
    icecat_product_id = fields.Char(
        string="Icecat Product ID",
        help="Icecat's internal numeric product ID (Product/@ID). Kept to "
        "identify this exact Icecat record when refreshing.",
        copy=False,
    )
    icecat_prod_id = fields.Char(
        string="Icecat Part Number",
        help="Manufacturer part number as known by Icecat (Product/@Prod_id), "
        "used together with the brand's Icecat manufacturer to refresh this "
        "product's data.",
        copy=False,
    )

    def action_icecat_refresh(self):
        """Re-fetch this product from Icecat and refresh its eCommerce
        description and main image.

        This does not touch categories or the additional image gallery, to
        avoid silently duplicating or reshuffling data a user may have
        curated by hand since the original import.
        """
        for product in self:
            manufacturer = product.product_brand_id.icecat_manufacturer_id
            if not product.icecat_prod_id or not manufacturer:
                raise UserError(
                    self.env._(
                        "%(name)s cannot be refreshed from Icecat: it needs "
                        "both an Icecat part number and a brand with an "
                        "Icecat manufacturer configured on its Icecat tab.",
                        name=product.display_name,
                    )
                )
            try:
                client = get_client_from_env(self.env)
                icecat_product = client.get_product_by_part_number(
                    product.icecat_prod_id, manufacturer.name
                )
            except IcecatError as exc:
                raise UserError(str(exc)) from exc

            product.icecat_product_id = icecat_product.icecat_id
            product.public_description = icecat_product.build_description_html()

            if manufacturer.import_main_image and icecat_product.main_image_url:
                image_bytes = self._icecat_download_image(icecat_product.main_image_url)
                if image_bytes:
                    product.image_1920 = image_bytes
        return True

    # ------------------------------------------------------------------
    # shared creation logic: used by the icecat.product.import wizard
    # (single part number) and icecat.import.line (bulk queue processor)
    # ------------------------------------------------------------------
    @api.model
    def _icecat_create_product(  # pylint: disable=too-many-positional-arguments
        self,
        name,
        part_number,
        ean,
        product_brand,
        icecat_id,
        description_html,
        category_icecat_id,
        category_name,
        main_image_url,
        gallery_image_urls,
        import_main_image,
        import_gallery_images,
        create_product_category,
        create_ecommerce_category,
    ):
        """Create one product.template from already-fetched Icecat data.

        Both callers (the ``icecat.product.import`` wizard and
        ``icecat.import.line._process``) always pass every argument by
        keyword; this is a wide parameter list because it is, deliberately,
        the full set of already-parsed fields for one Icecat product plus
        the import switches, kept as plain parameters rather than a
        dict/dataclass so each one stays typed and documented at the call
        site.

        Both callers are expected to have already resolved ``product_brand``
        to a brand with an Icecat manufacturer configured; this method does
        not re-validate that on its own.
        """
        product = self.create(
            {
                "name": name or part_number,
                "default_code": part_number,
                "barcode": ean or False,
                "product_brand_id": product_brand.id,
                "icecat_product_id": icecat_id,
                "icecat_prod_id": part_number,
                "public_description": description_html,
                "sale_ok": True,
            }
        )

        if category_icecat_id:
            icecat_category = (
                self.env["icecat.category"]
                .sudo()
                .get_or_create_category(category_icecat_id, category_name)
            )
            product.icecat_category_id = icecat_category.id
            if create_product_category:
                product.categ_id = icecat_category._get_or_create_product_category().id
            if create_ecommerce_category:
                product.public_categ_ids = [
                    (4, icecat_category._get_or_create_ecommerce_category().id)
                ]

        if import_main_image and main_image_url:
            image_bytes = product._icecat_download_image(main_image_url)
            if image_bytes:
                product.image_1920 = image_bytes

        if import_gallery_images and gallery_image_urls:
            product_image_model = self.env["product.image"].sudo()
            sequence = 10
            for url in gallery_image_urls:
                url = (url or "").strip()
                if not url or url == main_image_url:
                    continue
                image_bytes = product._icecat_download_image(url)
                if not image_bytes:
                    continue
                product_image_model.create(
                    {
                        "name": product.name,
                        "product_tmpl_id": product.id,
                        "image_1920": image_bytes,
                        "sequence": sequence,
                    }
                )
                sequence += 10

        return product

    def _icecat_download_image(self, url):
        try:
            response = requests.get(url, timeout=20)
            if response.status_code == 200:
                return base64.b64encode(response.content)
        except requests.exceptions.RequestException:
            _logger.warning("Icecat: failed to download image %s", url)
        return False
