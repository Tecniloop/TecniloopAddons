# -*- coding: utf-8 -*-
{
    'name': "Productos Opcionales",

    'summary': "Este modulo permite especificar productos opcionales tanto en categorias como en la ficha del producto",

    'description': """
        Este modulo permite especificar productos opcionales tanto en categorias como en la ficha del producto, tambien incluye la posibilidad de añadir productos CANON informados 
        en la caracteristica del producto (Modulo 'tl_conn_a3erp')
    """,
    'author': "Tecniloop",
    'website': "https://tecniloop.com",    
    'category': 'Sales',
    'version': '19.0.1.0.3',
    'depends': ['base', 'sale', 'contacts'],
    'data': [
        'views/product_category_views.xml',
        #'views/res_config_settings_views.xml',
        'views/product_template_views.xml',
        'views/res_partner_views.xml',
    ],
}

