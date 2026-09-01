# Tests and CI

```bash
odoo-bin -d DB -i tl_vendor_parseur_intake --test-tags=/tl_vendor_parseur_intake --stop-after-init
```

Or from this addon:

```bash
chmod +x scripts/run_tests.sh
ADDONS_PATH=/path/to/addons DB=test ./scripts/run_tests.sh
```

## Pipeline

Copy these files to the **repository root** if the git repo is not this addon folder:

- `.github/workflows/tests.yml` (GitHub Actions)
- `.gitlab-ci.yml` (GitLab CI)

Both start PostgreSQL 16, install the module in Odoo 19 and run
`--test-tags=/tl_vendor_parseur_intake`.

HttpCase tests (`test_webhook.py`) need the HTTP stack; they run with
`--test-enable` as above.

The official `odoo:19.0` image must match your build. If the image name
differs, change it in the workflow.
