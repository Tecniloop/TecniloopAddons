# -*- coding: utf-8 -*-
{
    'name': "Crear campo selection etapas MST",

    'summary': "Muestra el campo seleccion de las etapas MST",

    'description': """
        Este módulo crea un campo selection para las etapas MST.
    """,

    'author': "Tecniloop",
    'website': "https://www.tecniloop.es",

    'category': 'Accounting',
    'version': '18.0.1.0.1',

    'depends': ['base', 'sale'],

    'data': [
        'views/etapas_mst_views.xml',
    ],
}
