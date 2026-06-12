# -*- coding: utf-8 -*-
{
    'name': "TL - View All Messages",

    'summary': "Ver todos los mensajes de cada uno de los clientes en una sola vista",

    'description': """
        Ver todos los mensajes de cada uno de los clientes en una sola vista.
    """,

    'author': "Tecniloop",
    'website': "https://www.tecniloop.es",

    'category': 'Sales',
    'license': 'AGPL-3',
    'version': '18.0.1.0.2',
    'depends': ['base', 'mail', 'contacts'],
    
    'data': [
        'views/res_partner_views.xml',
        'views/mail_message_views.xml',
    ],

    'installable': True,
}

