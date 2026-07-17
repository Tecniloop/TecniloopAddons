from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    nextmart_partner_key = fields.Char(
        string="Nextmart Partner Key",
        config_parameter="website.nexmart_apikey",
        help=(
            "Partner key used in Nextmart DataView URLs. The legacy parameter "
            "from website_sale_nexmart v12 is reused for compatibility."
        ),
    )
    nextmart_language = fields.Selection(
        selection=[
            ("es", "Spanish"),
            ("ca", "Catalan"),
            ("en", "English"),
            ("fr", "French"),
            ("de", "German"),
            ("it", "Italian"),
            ("pt", "Portuguese"),
            ("nl", "Dutch"),
        ],
        string="Nextmart Language",
        default="es",
        config_parameter="tl_product_nextmart.language",
        required=True,
    )
    nextmart_update_name = fields.Boolean(
        string="Update Product Name",
        default=True,
        config_parameter="tl_product_nextmart.update_name",
        help="Replace the Odoo product name with the name returned by Nextmart.",
    )
    nextmart_overwrite_content = fields.Boolean(
        string="Overwrite Existing Content",
        default=False,
        config_parameter="tl_product_nextmart.overwrite_content",
        help=(
            "When disabled, descriptions, images, brand and manufacturer are "
            "only completed when they are empty. The product name follows its "
            "own setting."
        ),
    )
    nextmart_import_images = fields.Boolean(
        string="Import Images",
        default=True,
        config_parameter="tl_product_nextmart.import_images",
    )
    nextmart_import_all_images = fields.Boolean(
        string="Import All Nextmart Images",
        default=True,
        config_parameter="tl_product_nextmart.import_all_images",
        help=(
            "Import every unique image exposed by Nextmart, including product, "
            "packaging, dimensions, applications, details, icons and GPSR "
            "labels. The main image is stored on the product and the remaining "
            "images in the Odoo eCommerce gallery."
        ),
    )
    nextmart_import_specifications = fields.Boolean(
        string="Import Technical Specifications",
        default=True,
        config_parameter="tl_product_nextmart.import_specifications",
    )
    nextmart_create_brand_manufacturer = fields.Boolean(
        string="Create Brand and Manufacturer",
        default=True,
        config_parameter="tl_product_nextmart.create_brand_manufacturer",
        help=(
            "Automatically create the OCA product brand and its related "
            "manufacturer partner when no matching record exists."
        ),
    )
    nextmart_include_specs_ecommerce = fields.Boolean(
        string="Include Specifications in eCommerce Description",
        default=True,
        config_parameter="tl_product_nextmart.include_specs_ecommerce",
    )
    nextmart_max_extra_images = fields.Integer(
        string="Maximum Extra Images",
        default=12,
        config_parameter="tl_product_nextmart.max_extra_images",
    )
    nextmart_auto_show_iframe = fields.Boolean(
        string="Show DataView after Import",
        default=True,
        config_parameter="tl_product_nextmart.auto_show_iframe",
        help=(
            "Automatically enable the Nextmart iframe on the eCommerce product "
            "page after a successful enrichment."
        ),
    )
    nextmart_iframe_height = fields.Integer(
        string="DataView Iframe Height (px)",
        default=1800,
        config_parameter="tl_product_nextmart.iframe_height",
        help="Height of the Nextmart iframe on the public product page.",
    )
    nextmart_timeout = fields.Integer(
        string="Connection Timeout (seconds)",
        default=20,
        config_parameter="tl_product_nextmart.timeout",
    )


