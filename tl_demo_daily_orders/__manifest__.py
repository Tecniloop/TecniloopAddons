{
    "name": "Pedidos demo diarios (compra y venta)",
    "version": "19.0.1.2.0",
    "category": "Sales",
    "summary": "Pedidos demo por fechas, albaranes a fecha pasada y facturación el mismo día",
    "author": "Tecniloop",
    "license": "LGPL-3",
    "depends": ["sale_management", "purchase", "stock", "account", "queue_job"],
    "data": [
        "security/ir.model.access.csv",
        "views/demo_orders_wizard_views.xml",
    ],
    "installable": True,
    "application": False,
}
