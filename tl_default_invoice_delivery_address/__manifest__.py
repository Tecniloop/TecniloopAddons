# -*- coding: utf-8 -*-

{
    'name': "Direcciones de Facturación y Envío por Defecto en Pedidos de Venta",
    'author': 'Tecniloop',
    'category': 'Sales',
    'summary': """Direcciones de Facturación y Envío por Defecto en Pedidos de Venta""",
    'license': 'AGPL-3',
    'website': 'http://www.tecniloop.com',
    'description': """
        Este modulo filtra automaticamente las direcciones de facturación y envío en los pedidos de venta, según el cliente seleccionado
    """,
    'version': '19.0.1.0.1',
    'depends': ['sale_management'],
    'data': ["views/sale_order_views.xml"],
    'installable': True,
    'application': True,
    'auto_install': False,
}
