Install ``l10n_es_deca`` and OCA ``l10n_es_aeat`` first. The embedded signer
requires Odoo 19 on Python 3.12 or newer and ``pyHanko==0.24.*``. The pre-install
hook rejects incompatible Python or pyHanko versions instead of changing Odoo's
official cryptography dependency pins.

