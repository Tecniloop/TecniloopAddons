{
    "name": "TL BC3 Sale",
    "summary": "Generate Odoo quotations from BC3 budgets using native sale sections",
    "version": "19.0.1.0.1",
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
