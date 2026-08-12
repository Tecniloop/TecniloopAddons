* Set ``l10n_es_deca.public_base_url`` to the public HTTPS origin.
* Enforce TLS 1.2 or newer at the reverse proxy.
* Configure the public hostname and ``dbfilter`` so no database selector appears.
* Use the official Odoo 19 Python requirements.  The module supports the pinned
  ``PyPDF2`` runtime on Python 3.10--3.12 and ``PyPDF`` on Python 3.13+.
* Grant the DeCA User or DeCA Manager group to authorized stock users.
* Define an operational procedure for applicability, driver delivery, retention,
  trusted time, backups and public endpoint monitoring.
