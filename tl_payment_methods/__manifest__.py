# -*- coding: utf-8 -*-
{
    'name': "Mostrar detalle de condiciones de pago en factura",

    'summary': "Muestra el detalle de las cuotas incluso con un solo término de pago",

    'description': """
        Este módulo amplía el comportamiento estándar de Odoo para que
        en las facturas se muestre siempre el detalle de las cuotas de la
        condición de pago, incluso cuando solo existe un único término
        de vencimiento.
    """,

    'author': "Tecniloop",
    'website': "https://www.tecniloop.es",

    'category': 'Accounting',
    'version': '18.0.1.0.1',

    'depends': ['base', 'account'],

    'data': [
        'views/report_invoice.xml',
    ],
}
