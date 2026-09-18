{
    "name": "Pedidos demo diarios (compra y venta)",
    "version": "19.0.1.1.1",
    "category": "Sales",
    "summary": "Genera 3-7 pedidos de venta y compra por día (queue_job) con fechas de pedido y albarán pasadas",
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
