{
    "name": "eCommerce Same Category Product Carousel",
    "summary": "Adds a product carousel containing products from the current product categories",
    "version": "19.0.1.0.0",
    "category": "Website/eCommerce",
    "author": "Tecniloop",
    "website": "https://www.tecniloop.com",
    "license": "LGPL-3",
    "depends": ["website_sale"],
    "data": [
        "views/website_sale_templates.xml",
        "views/snippets.xml",
    ],
    "assets": {
        "web.assets_frontend": [
            "tl_website_sale_same_category_carousel/static/src/snippets/s_same_category_products/s_same_category_products.js",
        ],
        "website.website_builder_assets": [
            "tl_website_sale_same_category_carousel/static/src/website_builder/s_same_category_products_option.js",
            "tl_website_sale_same_category_carousel/static/src/website_builder/s_same_category_products_option.xml",
        ],
    },
    "installable": True,
    "application": False,
}
