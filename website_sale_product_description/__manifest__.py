# © 2020 Solvos Consultoría Informática (<http://www.solvos.es>)
# License AGPL-3 - See http://www.gnu.org/licenses/agpl-3.0.html
{
    "name": "Website Sale Product Description",
    "category": "Website",
    "summary": "Shows custom e-Commerce description for products",
    "description": """
Unofficial Odoo 19.0 compatibility patch
-----------------------------------------
This is the official OCA 17.0 module (see copyright/authors below) with one
change needed to install cleanly on Odoo 19.0, and no other changes:

* ``views/product_template.xml``: the xpath anchor ``group[@name='shop']``
  no longer exists in Odoo 19's product form (renamed to
  ``group[@name='extra_info']`` / "Ecommerce Shop"); updated accordingly.

Replace this with the official OCA release once one targets 19.0.
""",
    "version": "19.0.1.0.0",
    "website": "https://github.com/OCA/e-commerce",
    "author": "Solvos, Odoo Community Association (OCA)",
    "license": "AGPL-3",
    "depends": ["website_sale"],
    "data": [
        "views/website_sale_template.xml",
        "views/product_template.xml",
    ],
    "demo": [
        "data/demo_website_sale_product_description.xml",
    ],
}
