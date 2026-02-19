# -*- coding: utf-8 -*-
{
    'name': "Modifica la vista de Informes y Portal",

    'summary': "Modifica la vista de Informes y Portal para mostrar descripción y producto por separado",

    'description': """
        Este módulo modifica la vista de los informes y del portal de ventas y facturación para mostrar el producto y la descripción por separado en las líneas de pedido de venta. 
        Diferencia entre el producto y la descripción basándose en el nombre del producto y el contenido de la línea de pedido.
        Esta modificación afecta tanto a:
            - Ventas: Informés y Portal
            - Compras: Informés
            - Facturación: Informés
        Al cargar el producto en la linea, añade el nombre del producto y la descripción de compra en líneas separadas, para poder editar a voluntad.
    """,

    'author': "Tecniloop",
    'website': "https://www.tecniloop.com",

    'category': 'Reports',
    'version': '19.0.1.0.1',

    'depends': ['base','sale','account','purchase'],

    'data': [
        'views/sale_order_portal_content.xml',
        'reports/sale_order_report.xml',
       # 'reports/account_move_report.xml',
       # 'reports/purchase_order_report.xml',
    ],
}

