{
    "name": "TL BC3 Certification",
    "summary": "BC3 work certifications linked to sale orders and customer invoices",
    "version": '19.0.1.0.5',
    "category": "Construction/BC3",
    "author": "Tecniloop",
    "website": "https://www.tecniloop.com",
    "license": "AGPL-3",
    "depends": ["account", "tl_bc3_sale"],
    "data": [
        "security/ir.model.access.csv",
        "views/bc3_certification_views.xml",
        "views/sale_order_views.xml",
        "views/account_move_views.xml",
        "views/bc3_menu_views.xml",
    ],
    "installable": True,
}
