# Copyright 2026 Custom Development
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
{
    "name": "Icecat Catalog Integration",
    "summary": "Import products, images and technical specifications from the Icecat open catalog",
    "version": "19.0.1.0.0",
    "category": "Sales/Sales",
    "development_status": "Beta",
    "author": "Custom Development",
    "license": "LGPL-3",
    "depends": [
        "product",
        "website_sale",
        "product_brand",
        "website_sale_product_description",
    ],
    "external_dependencies": {
        "python": ["requests"],
    },
    "data": [
        "security/ir.model.access.csv",
        "views/res_config_settings_views.xml",
        "views/icecat_manufacturer_views.xml",
        "views/icecat_category_views.xml",
        "views/icecat_import_line_views.xml",
        "views/product_brand_views.xml",
        "views/product_template_views.xml",
        "wizards/icecat_product_import_views.xml",
        "views/icecat_menus.xml",
        "data/ir_cron_data.xml",
    ],
    "images": ["static/description/icon.png"],
}
