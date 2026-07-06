# Migration notes for Odoo 19.0

This addon was migrated from the attached Odoo 18.0 `l10n_es_vat_book_oss` module to work with the attached Odoo 19.0 `l10n_es_vat_book` base module and the migrated `l10n_eu_oss_oca` dependency.

## Main changes

- Manifest version changed from `18.0.1.0.2` to `19.0.1.0.0`.
- The legacy manifest key `autoinstall` was replaced by Odoo's standard `auto_install`.
- The VAT book OSS tax-map extension now uses `env.ref(..., raise_if_not_found=False)` and unions OSS sale taxes into the issued VAT map line.
- OSS tax fee nullification is now robust for both simple and group taxes, and zeros `amount` and `deductible_amount` only during VAT book calculation context.
- Tests were adjusted to use the Odoo 19 chart-template helper `company._get_taxes_from_xmlids(...)` instead of hard-coded chart XML IDs.
- README/static links and translation metadata were updated from 18.0 to 19.0.

## Validation done outside Odoo

- Python syntax compilation.
- XML parsing.
- Manifest parsing and module-data checks.
- ZIP top-level addon-folder check.

A full Odoo 19 database install/update test is still required in an Odoo runtime with `l10n_es_vat_book` and `l10n_eu_oss_oca` installed.
