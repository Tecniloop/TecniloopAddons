# -*- coding: utf-8 -*-
{
    'name': "Complemento a3ERP",

    'summary': "Consultar linias de pedidos de compra que han sido facturadas.",

    'description': """
        
    """,

    'author': "Tecniloop",
    'website': "https://www.tecniloop.es",

    'category': 'Sales',
    'version': '19.0.1.0.1',

    'depends': [
        'sale',
        'purchase',
        'tl_conn_a3erp',
    ],

    'data': [
        'views/sale_order_view.xml',        
        'views/purchase_order_view.xml',        
    ],

}

