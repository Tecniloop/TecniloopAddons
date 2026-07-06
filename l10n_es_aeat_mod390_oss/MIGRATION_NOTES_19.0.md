# Migration notes for Odoo 19.0

This addon was migrated from the provided 18.0 `l10n_es_aeat_mod390_oss` source to Odoo 19.0.

## Scope

- Keep the addon as the OSS extension of `l10n_es_aeat_mod390`.
- Keep dependencies on `l10n_es_aeat_mod390` and `l10n_eu_oss_oca`.
- Align the addon metadata and links with the OCA 19.0 branch.

## OCA 19.0 compatibility notes

- The OCA 19.0 `l10n_es_aeat_mod390` base manifest includes the 2021, 2022, 2023, 2024, and 2025 export configurations. The 2025 main export configuration still points sub06 to `aeat_mod390_2021_sub06_export_config`, so the existing override of `aeat_mod390_2021_sub06_export_line_37` remains the right central place for field 126 export.
- The parent model keeps `get_taxes_for_company(company)` and adds redirect logic for some base map lines. This addon keeps delegating to `super()` for all non-OSS map lines.
- The OSS tax detection still uses the `oss_country_id` field provided by `l10n_eu_oss_oca`.

## Changes made

- Bumped addon version to `19.0.1.0.0` and renamed the legacy `autoinstall` metadata key to Odoo's standard `auto_install`.
- Updated category to `Localisation/Accounting` to match the OCA 19.0 base module style.
- Reworked OSS map-line lookup to use `raise_if_not_found=False`, making the override safer during updates and partial data loads.
- Aligned the base tax-map CSV header with the OCA 19.0 base CSV order.
- Updated README/static documentation links and i18n POT metadata from 18.0 to 19.0.
- Made the test fallback to a 21% sale tax search if the chart-template XMLID is unavailable.

## Validation performed outside Odoo

- Python syntax compilation.
- XML parse validation.
- CSV row/header validation.
- Manifest parsing and data-file existence checks.

A full Odoo module installation/update test still needs to be run in an Odoo 19.0 database with the OCA 19.0 `l10n_es_aeat_mod390` addon and the migrated `l10n_eu_oss_oca` dependency installed.
