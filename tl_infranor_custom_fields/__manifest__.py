# -*- coding: utf-8 -*-
{
    'name': "Infranor - Campos personalizados",
    'summary': "Añade campos personalizados a los modelos de Infranor",
    'description': """
        Este módulo añade campos personalizados (custom fields) a los modelos
        de Odoo para adaptar el sistema a las necesidades específicas de Infranor.
    """,
    'author': "Tecniloop",
    'website': "https://www.tecniloop.es",
    'category': 'Sales',
    'version': '17.0.1.0.1',
    'depends': ['base', 'sale_management', 'sale_margin', 'sale_purchase', 'stock', 'sale_global_discount'],
    'data': [
        'views/sale_order_views.xml',
        'views/sale_order_line_views.xml',
        'views/product_template_views.xml',
    ],
    'installable': True,
    'application': False,
}
