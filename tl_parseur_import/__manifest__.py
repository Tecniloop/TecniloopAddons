# -*- coding: utf-8 -*-
{
    'name': "Parseur Import",

    'summary': "Modulo para recibir información del Parseur.",

    'description': """
        Este modulo recibe información de Parseur a partir de un documento escaneado.
        Al recibir la información del Parseur en formato JSON se crea en una tabla auxiliar para poder darse de alta como pedido de Venta en Odoo
    """,

    'author': "Tecniloop",
    'website': "https://www.tecniloop.es",

    'category': 'Sale',
    'version': '19.0.1.0.4',

    'depends': ['base','sale'],

    'data': [
        "security/ir.model.access.csv",
        "security/parseur_security.xml",
        "views/parseur_order_views.xml",
        "views/parseur_menu.xml",
        "views/res_config_settings_view.xml",
        "views/sale_order_view.xml",
        
        "wizards/assign_partner_wizard.xml",
    ],

}

