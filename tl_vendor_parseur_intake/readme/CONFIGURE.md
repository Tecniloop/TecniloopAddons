1. Purchase → Configuration: set the Parseur webhook token, quantity
   over-receipt policy and price tolerances.
2. Open each vendor and enable **Auto-validate Parseur receipts** when
   the warehouse may skip the manual Validate step for that supplier.
3. Point Parseur to `POST /parseur/vendor/intake` with header
   `X-Webhook-Token`.
4. For DEBUG traces: start Odoo with
   `--log-handler=odoo.addons.tl_vendor_parseur_intake:DEBUG`
   or set the logger to Debug in Settings → Technical → Logging.
