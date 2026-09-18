{
    "name": "Pedidos demo diarios (compra y venta)",
    "version": "19.0.1.0.1",
    "category": "Sales",
    "summary": "Genera 3-7 pedidos de venta y compra por día en un intervalo, con albaranes a fecha pasada",
    "author": "Tecniloop",
    "license": "LGPL-3",
    "depends": ["sale_management", "purchase", "stock", "account"],
    "data": [
        "security/ir.model.access.csv",
        "views/demo_orders_wizard_views.xml",
    ],
    "installable": True,
    "application": False,
}
