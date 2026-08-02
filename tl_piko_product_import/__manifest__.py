{
    "name": "PIKO Product Import (Web Scraping)",
    "summary": "Importador de productos por scraping de tiendas web sin API "
               "(piko-shop.de y similares), con staging previo",
    "version": "19.0.6.1.1",
    "category": "Sales/Sales",
    "author": "Tecniloop",
    "website": "https://www.tecniloop.com",
    "license": "LGPL-3",
    "depends": [
        "product",
        "mail",
        # necesario para product.public.category (categorías de eCommerce)
        "website_sale",
        # OCA: ejecución asíncrona (github.com/OCA/queue)
        "queue_job",
    ],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/queue_job_data.xml",
        "data/ir_cron.xml",
        "data/tl_piko_source_data.xml",
        "data/tl_piko_attribute_data.xml",
        "views/piko_source_views.xml",
        "views/piko_product_views.xml",
        "views/piko_attribute_rule_views.xml",
        "wizard/piko_import_wizard_views.xml",
        "views/product_template_views.xml",
        "views/menus.xml",
    ],
    "external_dependencies": {
        "python": ["requests", "lxml"],
    },
    "installable": True,
    "application": False,
}
