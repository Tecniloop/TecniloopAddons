{
    "name": "Website Sale: distintivos y disponibilidad",
    "summary": "Iconos de características sobre la imagen y punto de "
               "disponibilidad en la ficha y en el listado de la tienda",
    "version": "19.0.1.1.0",
    "category": "Website/Website",
    "author": "Tecniloop",
    "website": "https://www.tecniloop.com",
    "license": "LGPL-3",
    "depends": ["website_sale"],
    "data": [
        "views/product_attribute_views.xml",
        "views/product_template_views.xml",
        "views/website_sale_templates.xml",
    ],
    "assets": {
        "web.assets_frontend": [
            "tl_website_sale_product_badges/static/src/scss/badges.scss",
        ],
    },
    "installable": True,
}
