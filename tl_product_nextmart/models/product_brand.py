from odoo import fields, models


class ProductBrand(models.Model):
    _inherit = "product.brand"

    nextmart_supplier_id = fields.Char(
        string="Nextmart Supplier ID",
        index=True,
        copy=False,
        help="Supplier identifier returned in the Nextmart analytics block.",
    )
    nextmart_catalog_prefix = fields.Char(
        string="Nextmart Catalog Prefix",
        index=True,
        copy=False,
    )
    nextmart_logo_url = fields.Char(
        string="Nextmart Logo URL",
        copy=False,
    )
