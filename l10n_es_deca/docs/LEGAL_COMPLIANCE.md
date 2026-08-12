# Legal-to-technical control matrix

Status checked against consolidated BOE texts on 11 August 2026.

| Legal requirement | Module control | Evidence / residual risk |
|---|---|---|
| Essential data (Order FOM/2861/2012, art. 6) | Required structured fields and server-side issue validation | Applicability and factual accuracy remain with contractual shipper/effective carrier under art. 7. |
| Link to the operational service | Exactly one `stock.picking` per DeCA; a batch creates one document per picking and its reference is frozen in the version snapshot | Stock prefill is explicitly reviewable. A batch is not treated as one legal service because it may be multidestination. |
| Create before effective start (Resolution 2026, first.2) | Issuance timestamp is sealed; `Start transport` is impossible without a current sealed version | Actual start depends on the user pressing the workflow action at the true time. Operational procedure/GPS integration can strengthen evidence. |
| Native digital PDF, legible, max. 5 MB (second.1–2) | QWeb renders structured data; binary length is rejected above 5 MiB | Production font/rendering must be acceptance-tested with the deployed wkhtmltopdf/Chromium engine. |
| Creation/modification times as PDF metadata (second.1) | `pypdf` writes `/CreationDate` and `/ModDate` in UTC after QWeb rendering | Host time must be synchronized and monitored. |
| QR embedded in PDF (second.3) | QR PNG is generated from the frozen version URL and embedded by QWeb | Acceptance test should scan a real printed and mobile copy. |
| Keep files for at least one year (second.4; Order art. 9) | No version or delivery log can be changed/deleted through the ORM; public window is 366 days | Superuser/database/attachment storage and backups require infrastructure controls. |
| Unique HTTPS URL, TLS 1.2+ (third.1–2) | Unique 256-bit token; issue refuses non-HTTPS origin | TLS version/certificate are reverse-proxy responsibilities. |
| Direct PDF download, no credentials/manual interaction (third.3–4) | Public GET returns `application/pdf` with attachment disposition directly | Monitor the full public path through proxies/CDNs/WAF. |
| URL not expire before service end (third.2); may deactivate seven days after end (third.5) | Route remains available for 366 days and never expires while state is issued/in transit | Conservative availability is longer than the optional seven-day minimum; review privacy policy and repository-sharing model. |
| Signature not mandatory; AdES minimum if contractual signature is used (fourth) | No handwritten-signature validity state exists; contractual purpose fails closed in the base addon; `_postprocess_pdf` runs before the final hash seal | Optional `l10n_es_deca_ades` applies PAdES through pyHanko and reuses active company certificates from OCA `l10n_es_aeat`; independent trust, revocation, representation and AdES/QES qualification validation remains required. |
| Changes during service (fifth) | Revision wizard requires a reason and creates a new PDF/URL/QR; prior PDF, checksum and chain remain | New version must be delivered to the driver; the delivery log supports this procedure. |
| Copy/QR to driver before start (seventh) | Start action requires append-only evidence for the current version | Evidence records the declared method/recipient, not cryptographic receipt by the driver. |
| Canonical language policy | The QWeb statutory body is Spanish with translation disabled and report rendering forces `es_ES` context | UI translations do not alter the PDF. A bilingual statutory layout would require separate legal review. |

## Official sources

- [Law 9/2025, of 3 December, on Sustainable Mobility](https://www.boe.es/buscar/act.php?id=BOE-A-2025-24545)
- [Resolution of 5 June 2026 on electronic administrative control documents](https://www.boe.es/buscar/act.php?id=BOE-A-2026-12784)
- [Order FOM/2861/2012 on the administrative control document for public road freight](https://www.boe.es/buscar/act.php?id=BOE-A-2013-154)

## Acceptance checklist

- Confirm the system parameter resolves to the final public HTTPS origin.
- Verify TLS 1.2/1.3 and a trusted certificate from outside the corporate network.
- Issue a sample, inspect PDF metadata, verify size and scan the embedded QR.
- Create documents from one picking and a multidestination batch; confirm that the batch creates one DeCA per picking.
- Confirm a GET to the scanned URL returns status 200 and `application/pdf` directly in a clean browser without authentication.
- Repeat the test through every WAF/CDN/reverse-proxy layer.
- Create a revision during an in-transit test, verify a new URL/QR, and verify the old PDF hash is unchanged.
- Attempt write/delete operations as User and Manager roles.
- Confirm multi-company isolation.
- Restore the database and attachment store together from backup and re-check hashes.
- Document the one-year retention owner for both contractual shipper and effective carrier.
- If an optional signature addon is installed, validate the PAdES signature with an
  independent verifier and test certificate expiry/revocation/timestamp behaviour.
