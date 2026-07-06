# Odoo 19 migration notes for l10n_es_aeat_mod369

This package was forward-ported from the supplied Odoo 18.0 module to Odoo 19.0.

Changes applied:

- Bumped `__manifest__.py` from `18.0.1.0.1` to `19.0.1.0.0`.
- Kept dependencies as `l10n_es_aeat` and `l10n_eu_oss_oca`, matching the supplied Odoo 19 dependency modules.
- Updated report posting compute method to assign per record.
- Replaced account move line `move_type` access with explicit `move_id.move_type` checks for refund detection.
- Cleaned CSV data issues found in the supplied 18.0 ZIP: duplicate export-config header, extra empty cells in page 08 export lines, and three off-by-one refund period expressions.
- Updated README/static description links from 18.0 to 19.0.

Static checks performed:

- Python syntax compilation.
- XML syntax parsing.
- CSV header/row length validation.

Runtime installation still needs to be validated in a real Odoo 19 database with the required dependency modules installed.
