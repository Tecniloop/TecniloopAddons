{
    "name": "Website Product Search (Elasticsearch)",
    "version": "18.0.1.0.0",
    "summary": "Smart product search for Odoo eCommerce using Elasticsearch",
    "category": "Website/eCommerce",
    "author": "meet1432",
    "license": "LGPL-3",
    "images": ["static/description/icon.png"],
    "depends": ["website_sale", "website"],
    "data": [
        "security/ir.model.access.csv",
        "data/ir_cron.xml",
        "views/res_config_settings_view.xml",
        "views/es_dynamic_index_views.xml",
        "views/website_search_templates.xml",
        "views/website_badges_templates.xml",
        "views/product_template_badges_views.xml",
    ],
    "assets": {
        "web.assets_frontend": [
            "website_product_search_es/static/src/js/es_search.js",
            "website_product_search_es/static/src/css/es_search.css",
        ]
    },
    "post_init_hook": "post_init_hook",
    "installable": True,
    "application": True,
}
