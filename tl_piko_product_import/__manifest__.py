{
    "name": "PIKO Product Import (Web Scraping)",
    "summary": "Importador de productos por scraping de tiendas web sin API "
               "(piko-shop.de y similares), con staging previo",
    "version": "19.0.13.0.0",
    "category": "Sales/Sales",
    "author": "Tecniloop",
    "website": "https://www.tecniloop.com",
    "license": "LGPL-3",
    "depends": [
        "product",
        "mail",
        # necesario para product.public.category (categorías de eCommerce)
        "website_sale",
        # aporta la tabla #product_full_spec, junto a la que se muestran las
        # propiedades; sin él ese anclaje no existe
        "website_sale_comparison",
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
        "views/piko_product_actions.xml",
        "views/menus.xml",
        "templates/product_properties.xml",
    ],
    "external_dependencies": {
        "python": ["requests", "lxml"],
    },
    "installable": True,
    "application": False,
}
