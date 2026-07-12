# Copyright 2020 Tecnativa - Jairo Llopis
# Copyright 2021 Tecnativa - Víctor Martínez
# Copyright 2021 Tecnativa - Pedro M. Baeza
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
{
    "name": "eCommerce product attachments",
    "summary": "Let visitors download attachments from a product page",
    "description": """
Unofficial Odoo 19.0 compatibility patch
-----------------------------------------
This is the official OCA 17.0 module (see copyright/authors below) with two
changes needed to install cleanly on Odoo 19.0, and no other changes:

* ``views/product_template.xml``: the xpath anchor ``group[@name='shop']``
  no longer exists in Odoo 19's product form (renamed to
  ``group[@name='extra_info']`` / "Ecommerce Shop"); updated accordingly.
* Same file: its inline ``website_attachment_ids`` sub-view used the legacy
  ``<tree>`` tag, renamed to ``<list>`` in Odoo 17/18.

Replace this with the official OCA release once one targets 19.0.
""",
    "version": "19.0.1.0.0",
    "development_status": "Beta",
    "category": "Website",
    "website": "https://github.com/OCA/e-commerce",
    "author": "Tecnativa, Odoo Community Association (OCA)",
    "maintainers": ["Yajo"],
    "license": "LGPL-3",
    "depends": ["website_sale"],
    "data": [
        "templates/product_template.xml",
        "views/ir_attachment.xml",
        "views/product_template.xml",
    ],
    "assets": {
        "web.assets_tests": [
            "website_sale_product_attachment/static/tests/tours/website_tour.esm.js",
        ]
    },
}
