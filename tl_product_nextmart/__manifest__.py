{
    "name": "Product Nextmart Enrichment",
    "summary": "Complete product data from Nextmart using the product GTIN/EAN",
    "version": "19.0.1.1.0",
    "category": "Product",
    "author": "Tecniloop",
    "website": "https://www.tecniloop.com",
    "license": "AGPL-3",
    "depends": [
        "base_setup",
        "website_sale",
        "product_brand",
        "product_manufacturer",
    ],
    "external_dependencies": {
        "python": ["lxml", "requests"],
    },
    "data": [
        "security/ir.model.access.csv",
        "views/res_config_settings_views.xml",
        "views/product_brand_views.xml",
        "views/product_template_views.xml",
        "views/website_sale_templates.xml",
    ],
    "assets": {
        "web.assets_frontend": [
            "tl_product_nextmart/static/src/css/nextmart.css",
        ],
    },
    "installable": True,
    "application": False,
}
