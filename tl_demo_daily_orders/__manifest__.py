{
    "name": "Pedidos demo diarios (compra y venta)",
    "version": "19.0.1.5.2",
    "category": "Sales",
    "summary": "Pedidos, facturas y leads demo por fechas",
    "author": "Tecniloop",
    "license": "LGPL-3",
    "depends": ["sale_management", "purchase", "stock", "account", "crm", "queue_job"],
    "data": [
        "security/ir.model.access.csv",
        "views/demo_orders_wizard_views.xml",
    ],
    "installable": True,
    "application": False,
}
