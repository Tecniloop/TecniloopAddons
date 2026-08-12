# Architecture and optional integrations

## Stock document boundary

The base addon creates one DeCA for one `stock.picking`. A
`stock.picking.batch` is an operational grouping and creates one DeCA per eligible
transfer because a batch may contain different destinations or transport services.

Stock data is only a draft suggestion. The operator remains responsible for
confirming the contractual shipper, effective carrier, route, goods, weight,
vehicle and applicability before issuing the document.

## Native core and external services

The base addon owns the statutory document lifecycle:

- canonical Spanish PDF and embedded QR;
- direct, opaque public PDF URL;
- immutable versions, timestamps, checksums and hash chain;
- append-only evidence that the PDF or QR was delivered to the driver;
- stock-picking and batch-picking traceability.

SMS, WhatsApp, mobile applications, qualified trust services, external timestamp
authorities and immutable object stores belong in optional glue addons. They are
useful operational controls, but are not conditions for the administrative DeCA
itself.

## Certificates and PAdES

OCA 19.0 stores the certificate used by AEAT/SII in `l10n_es_aeat`, model
`l10n.es.aeat.certificate`. Its `get_certificates()` method selects the active,
in-date certificate for a company and returns the public-certificate and private-key
PEM paths.

That model is suitable as an optional source of certificate material, but it is not
a PDF-signing engine. The optional `l10n_es_deca_ades` glue addon therefore:

1. depend on `l10n_es_deca` and `l10n_es_aeat`;
2. select the certificate through `get_certificates(company)`;
3. implements PAdES with pyHanko and, when configured, an
   external timestamp or qualified trust service;
4. overrides `_postprocess_pdf(pdf, version)` and returns the signed PDF;
5. exposes signer, certificate fingerprint, signature profile and validation result
   as immutable evidence.

The hook runs after canonical PDF metadata is written and before size, SHA-256 and
hash-chain seals are calculated. A signing addon must never mutate a sealed version.

Do not equate these different controls:

- a drawn signature on a phone is evidence capture, not automatically AdES;
- a company server seal is not a driver's or counterparty's signature;
- a timestamp proves a time assertion but does not by itself prove consent;
- the AEAT certificate store does not by itself produce or validate PAdES.

No accounting or AEAT dependency is added to the base Inventory addon. The
optional signing addon carries that dependency explicitly.
