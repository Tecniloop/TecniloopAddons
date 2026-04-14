# l10n_firma_electronica/__manifest__.py
{
    'name': 'Digital Signature with Certificates',
    'version': '17.0.1.0.0',
    'category': 'Tools',
    'summary': 'Digitally sign documents with assigned electronic certificates',
    'description': """
        Provides a secure digital-signing flow for Odoo reports using assigned
        electronic certificates (FNMT, DNIe, and compatible P12/PFX files).

        Features:
            - Certificate-based digital signatures
            - Document integrity guarantees
            - Signer authentication
            - Advanced e-signature legal validity
            - Certificate assignment management
        """,
    'author': 'Raúl Bonito Vázquez',
    'maintainer': 'Raúl Bonito Vázquez',
    'website': 'https://github.com/raulbonito',
    'depends': [
        'base',
        'web',
        'mail',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/certificate_views.xml',
        'views/signature_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'l10n_firma_electronica/static/src/scss/signature_dialog.scss',
            'l10n_firma_electronica/static/src/xml/signature_dialog.xml',
            'l10n_firma_electronica/static/src/js/signature_dialog.js',
            'l10n_firma_electronica/static/src/js/signature_handler.js',
        ],
    },
    'external_dependencies': {
        'python': [
            'psycopg2',
            'pyHanko',
            'cryptography',
            'pyOpenSSL',
            'certifi',
            'requests',
            'lxml',
            'pytz',
        ]
    },
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
    'sequence': -100,
}
