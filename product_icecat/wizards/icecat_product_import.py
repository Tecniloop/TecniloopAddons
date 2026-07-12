# Copyright 2026 Custom Development
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
from odoo import api, fields, models
from odoo.exceptions import UserError

from ..models.icecat_api import IcecatError, get_client_from_env


class IcecatProductImport(models.TransientModel):
    _name = "icecat.product.import"
    _description = "Import a Product from Icecat"

    state = fields.Selection(
        [("search", "Search"), ("preview", "Preview")], default="search", required=True
    )

    part_number = fields.Char(
        help="Manufacturer part number (Icecat Prod_ID) to look up."
    )
    product_brand_id = fields.Many2one(
        comodel_name="product.brand",
        string="Brand",
        help="Brand of the product. Its Icecat tab must be linked to an "
        "Icecat manufacturer.",
    )
    icecat_manufacturer_id = fields.Many2one(
        related="product_brand_id.icecat_manufacturer_id", readonly=True
    )

    # -- fetched data, populated by action_search(), read-only preview -----
    fetched_icecat_id = fields.Char(readonly=True)
    fetched_prod_id = fields.Char(readonly=True)
    fetched_name = fields.Char(readonly=True)
    fetched_short_description = fields.Text(readonly=True)
    fetched_ean = fields.Char(readonly=True)
    fetched_category_icecat_id = fields.Char(readonly=True)
    fetched_category_name = fields.Char(readonly=True)
    fetched_description_html = fields.Html(readonly=True)
    fetched_main_image_url = fields.Char(readonly=True)
    fetched_gallery_image_urls = fields.Text(readonly=True)
    fetched_image_preview = fields.Image(readonly=True, max_width=256, max_height=256)

    # -- import options, pre-filled from the manufacturer, editable here ---
    import_main_image = fields.Boolean(default=True)
    import_gallery_images = fields.Boolean(string="Import Additional Images")
    create_product_category = fields.Boolean()
    create_ecommerce_category = fields.Boolean(string="Create eCommerce Category")

    @api.onchange("product_brand_id")
    def _onchange_product_brand_id(self):
        for wizard in self:
            manufacturer = wizard.product_brand_id.icecat_manufacturer_id
            if manufacturer:
                wizard.import_main_image = manufacturer.import_main_image
                wizard.import_gallery_images = manufacturer.import_gallery_images
                wizard.create_product_category = manufacturer.create_product_category
                wizard.create_ecommerce_category = manufacturer.create_ecommerce_category

    # ------------------------------------------------------------------
    def _reopen(self):
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }

    def action_search(self):
        self.ensure_one()
        if not self.part_number or not self.part_number.strip():
            raise UserError(self.env._("Please enter a part number."))
        if not self.product_brand_id:
            raise UserError(self.env._("Please select a brand."))
        if not self.icecat_manufacturer_id:
            raise UserError(
                self.env._(
                    "The brand %(brand)s has no Icecat manufacturer "
                    "configured. Open the brand and set one on its Icecat "
                    "tab first.",
                    brand=self.product_brand_id.name,
                )
            )

        try:
            client = get_client_from_env(self.env)
            icecat_product = client.get_product_by_part_number(
                self.part_number.strip(), self.icecat_manufacturer_id.name
            )
        except IcecatError as exc:
            raise UserError(str(exc)) from exc

        image_preview = False
        if icecat_product.main_image_url:
            image_preview = self.env["product.template"]._icecat_download_image(
                icecat_product.main_image_url
            )

        self.write(
            {
                "state": "preview",
                "fetched_icecat_id": icecat_product.icecat_id,
                "fetched_prod_id": icecat_product.prod_id,
                "fetched_name": icecat_product.title,
                "fetched_short_description": icecat_product.short_description,
                "fetched_ean": icecat_product.ean,
                "fetched_category_icecat_id": icecat_product.category_icecat_id,
                "fetched_category_name": icecat_product.category_name,
                "fetched_description_html": icecat_product.build_description_html(),
                "fetched_main_image_url": icecat_product.main_image_url,
                "fetched_gallery_image_urls": "\n".join(icecat_product.gallery_image_urls),
                "fetched_image_preview": image_preview,
            }
        )
        return self._reopen()

    def action_back(self):
        self.ensure_one()
        self.state = "search"
        return self._reopen()

    def action_import(self):
        self.ensure_one()
        if not self.fetched_prod_id and not self.fetched_icecat_id:
            raise UserError(self.env._("Please search a product before importing it."))

        product = self.env["product.template"]._icecat_create_product(
            name=self.fetched_name,
            part_number=self.part_number,
            ean=self.fetched_ean,
            product_brand=self.product_brand_id,
            icecat_id=self.fetched_icecat_id,
            description_html=self.fetched_description_html,
            category_icecat_id=self.fetched_category_icecat_id,
            category_name=self.fetched_category_name,
            main_image_url=self.fetched_main_image_url,
            gallery_image_urls=(
                self.fetched_gallery_image_urls.splitlines()
                if self.fetched_gallery_image_urls
                else []
            ),
            import_main_image=self.import_main_image,
            import_gallery_images=self.import_gallery_images,
            create_product_category=self.create_product_category,
            create_ecommerce_category=self.create_ecommerce_category,
        )

        return {
            "type": "ir.actions.act_window",
            "res_model": "product.template",
            "res_id": product.id,
            "view_mode": "form",
            "target": "current",
        }
