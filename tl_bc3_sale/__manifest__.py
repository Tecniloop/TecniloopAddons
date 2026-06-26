{
    "name": "TL BC3 Venta",
    "summary": "Genera presupuestos de venta de Odoo desde presupuestos BC3 usando secciones nativas",
    "version": "19.0.1.1.0",
    "category": "Construction/BC3",
    "author": "Tecniloop",
    "website": "https://www.tecniloop.com",
    "license": "AGPL-3",
    "depends": ["sale", "tl_bc3_budget"],
    "data": [
        "security/ir.model.access.csv",
        "data/product_data.xml",
        "views/sale_order_views.xml",
        "views/bc3_budget_views.xml",
    ],
    "installable": True,
}
