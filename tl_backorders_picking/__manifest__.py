{
    'name': "Mostrar entregas parciales en OUT",

    'summary': "Este modulo añade en los albaranes de entrega OUT las cantidades parciales no entregadas en PICK, en caso de trabajar con 2 pasos.",

    'description': """
        Este modulo añade en los albaranes de entrega OUT las cantidades parciales no entregadas en PICK, en caso de trabajar con 2 pasos.
        Odoo cuando trabaja con dos pasos de entrega, genera un albarán de entrega OUT y otro albarán de entrega PICK. 
        En el albarán de entrega OUT no se muestran las cantidades parciales que no se han entregado en el albarán de entrega PICK, este módulo añade esas cantidades parciales en el albarán de entrega OUT.
    """,

    'author': "Tecniloop",
    'website': "https://www.tecniloop.es",

    'category': 'Reports',
    'version': '19.0.1.0.1',

    'depends': [        
        'stock',
    ],

    'data': [
        "reports/report_picking_inherit.xml",
    ],
}

