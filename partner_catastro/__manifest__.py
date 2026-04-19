{
    'name': 'Partner Catastro',
    'version': '18.0.1.0.1',
    'summary': 'Consulta datos del Catastro desde res.partner',
    'description': '''
Partner Catastro
================

Añade una pestaña "Catastro" en los contactos y un wizard para consultar
los servicios web libres del Catastro a partir de una referencia catastral.

Características:
- Consulta de datos no protegidos por referencia catastral.
- Consulta opcional de coordenadas por finca (14 posiciones).
- Almacenamiento de resumen, payload bruto y todos los campos/valores devueltos.
- URLs y timeout configurables desde Ajustes.
''',
    'author': 'OpenAI',
    'website': 'https://www.odoo.com',
    'category': 'Contacts',
    'license': 'LGPL-3',
    'depends': ['base', 'contacts'],
    'external_dependencies': {
        'python': ['requests'],
    },
    'data': [
        'security/ir.model.access.csv',
        'views/res_config_settings_views.xml',
        'views/res_partner_views.xml',
        'views/res_partner_catastro_wizard_views.xml',
    ],
    'installable': True,
    'application': False,
}
