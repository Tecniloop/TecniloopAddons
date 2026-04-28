# Copyright 2026 APEN Solutions
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0.en.html).

{
    "name": "Website Sale - Search by brand and attribute values",
    "summary": "Extends website product search across brands, attributes, tags and categories",
    "version": "18.0.2.0.1",
    "category": "Website/Website",
    "author": "APEN Solutions, OCA",
    "website": "",
    "license": "LGPL-3",
    "depends": [
        "website_sale",
        "product",
        "website_product_brands",
    ],
    "data": [
        "views/res_config_settings_views.xml",
    ],
    "installable": True,
    "application": False,
    "maintainers": ["jaume"],
}
