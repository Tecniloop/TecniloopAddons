# Copyright 2026 Custom Development
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
from odoo import api, fields, models


class IcecatManufacturer(models.Model):
    _name = "icecat.manufacturer"
    _description = "Icecat Manufacturer"
    _order = "name"

    name = fields.Char(
        required=True,
        help="Exact manufacturer/vendor name as known by Icecat. This is "
        "sent as the 'vendor' parameter when querying the Icecat API, so "
        "it must match Icecat's own spelling (e.g. as seen in their "
        "supplier mapping export).",
    )
    icecat_supplier_id = fields.Char(
        string="Icecat Supplier ID",
        help="Icecat's internal numeric Supplier ID. Not needed for "
        "single-part-number imports, but required to bulk-import all of "
        "this manufacturer's products (it's how matching entries are found "
        "in Icecat's catalog index).",
    )
    active = fields.Boolean(default=True)

    product_brand_ids = fields.One2many(
        comodel_name="product.brand",
        inverse_name="icecat_manufacturer_id",
        string="Linked Brands",
    )
    brand_count = fields.Integer(compute="_compute_brand_count")

    # -- import configuration ------------------------------------------------
    import_main_image = fields.Boolean(
        default=True,
        help="When importing a product from this manufacturer, set Icecat's "
        "main picture as the product image.",
    )
    import_gallery_images = fields.Boolean(
        string="Import Additional Images",
        default=True,
        help="When importing a product from this manufacturer, import "
        "Icecat's additional pictures as extra website media (product "
        "gallery images shown on the eCommerce product page).",
    )
    create_product_category = fields.Boolean(
        default=False,
        help="When importing a product from this manufacturer, get or "
        "create a Product Category matching its Icecat category, and set "
        "it on the product.",
    )
    create_ecommerce_category = fields.Boolean(
        string="Create eCommerce Category",
        default=False,
        help="When importing a product from this manufacturer, get or "
        "create a Website/eCommerce Category matching its Icecat category, "
        "and add it to the product.",
    )

    _sql_constraints = [
        ("name_uniq", "unique(name)", "This Icecat manufacturer name already exists."),
    ]

    @api.depends("product_brand_ids")
    def _compute_brand_count(self):
        for manufacturer in self:
            manufacturer.brand_count = len(manufacturer.product_brand_ids)

    def action_view_brands(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Brands"),
            "res_model": "product.brand",
            "view_mode": "list,form",
            "domain": [("icecat_manufacturer_id", "=", self.id)],
            "context": {"default_icecat_manufacturer_id": self.id},
        }
