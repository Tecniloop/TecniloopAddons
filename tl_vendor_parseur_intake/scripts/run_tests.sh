#!/bin/sh
# Run tl_vendor_parseur_intake Odoo tests.
# Usage:
#   ODOO_BIN=/opt/odoo/odoo-bin DB=test ./scripts/run_tests.sh
#   docker compose / CI should set PGHOST, PGUSER, PGPASSWORD.

set -eu

MODULE="${MODULE:-tl_vendor_parseur_intake}"
DB="${DB:-tl_parseur_test}"
ODOO_BIN="${ODOO_BIN:-odoo}"
ADDONS_PATH="${ADDONS_PATH:-.}"
ODOO_CFG="${ODOO_CFG:-}"

if [ -n "$ODOO_CFG" ]; then
  CFG_ARG="--config=$ODOO_CFG"
else
  CFG_ARG=""
fi

$ODOO_BIN $CFG_ARG \
  --db_host="${PGHOST:-localhost}" \
  --db_port="${PGPORT:-5432}" \
  --db_user="${PGUSER:-odoo}" \
  --db_password="${PGPASSWORD:-odoo}" \
  -d "$DB" \
  --addons-path="$ADDONS_PATH" \
  --http-interface=127.0.0.1 \
  --http-port="${ODOO_PORT:-8069}" \
  -i "$MODULE" \
  --test-enable \
  --test-tags="/$MODULE" \
  --stop-after-init \
  --workers=0 \
  --max-cron-threads=0 \
  --log-level=test
