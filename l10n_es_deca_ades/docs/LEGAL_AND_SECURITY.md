# Contractual signing control matrix

Status reviewed on 11 August 2026.

| Requirement or risk | Control | Residual limitation |
|---|---|---|
| DeCA also used contractually and signatures are included | Contractual purpose fails closed unless the signing addon is installed and all configured signatures are embedded | Whether signatures are required for the specific contract remains a legal/operational decision |
| At least AdES when signatures are included | PAdES subfilter, SHA-256 digest and cryptographic integrity validation | PAdES is a container/profile; AdES/QES qualification is not inferred from certificate possession |
| Correct contracting parties | Each signing company commercial partner must match the contractual shipper/effective carrier partner | Organizational authority and representative capacity require external evidence |
| No unauthorized private-key use | Dedicated signer group, allowed-company check, party binding, then narrowly elevated certificate lookup | Local PEM keys remain available to the Odoo worker process; HSM/remote-signature adapters are preferable |
| Trusted time | Optional PAdES B-T requires an RFC 3161 TSA URL | TSA trust/revocation must be independently validated |
| Immutable final evidence | PAdES is applied before PDF size, SHA-256 and hash-chain seals | Database, attachment store and backup immutability remain infrastructure controls |
| Revisions | Every revision creates a new URL/QR/PDF and repeats the full signing policy | Counterparties must consent again under the applicable contractual process |

## Company defaults

Each operational company chooses the policy copied to newly created DeCA
drafts:

- `Administrative only (no signature)` keeps the statutory DeCA unsigned.
- `Administrative and contractual (PAdES required)` blocks issue until the
  configured shipper/carrier signatures have been embedded and validated.

The default signature roles and signing companies are initial values only. An
authorized operator may change them while the DeCA is a draft. Later changes to
company settings never rewrite an existing draft or an immutable issued version.

## Runtime compatibility

The in-process signer is deliberately limited to Odoo 19 on Python 3.12 or newer
with pyHanko 0.24.x. Odoo 19 pins `cryptography==42.0.8` on Python 3.12+, while
pyHanko 0.24.0 requires `cryptography>=42.0.1`; those constraints intersect.
Odoo pins `cryptography==3.4.8` below Python 3.12, so the in-process dependency
graphs do not intersect there. The pre-install hook rejects unsupported
combinations instead of silently replacing an Odoo core pin.

## Official and primary references

- Resolution of 5 June 2026, section four: <https://www.boe.es/buscar/act.php?id=BOE-A-2026-12784>
- Regulation (EU) 910/2014 (eIDAS), article 26: <https://eur-lex.europa.eu/eli/reg/2014/910/oj>
- pyHanko signing documentation: <https://docs.pyhanko.eu/en/stable/lib-guide/signing.html>
- OCA ``l10n_es_aeat`` certificate model: <https://github.com/OCA/l10n-spain/blob/19.0/l10n_es_aeat/models/aeat_certificate.py>
- Odoo 19 official Python requirements: <https://github.com/odoo/odoo/blob/19.0/requirements.txt>
