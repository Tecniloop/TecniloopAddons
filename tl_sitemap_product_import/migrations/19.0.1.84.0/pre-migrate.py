from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    cr.execute("""
        ALTER TABLE sitemap_import_source
        ADD COLUMN IF NOT EXISTS shopify_js_mode varchar,
        ADD COLUMN IF NOT EXISTS shopify_js_status varchar,
        ADD COLUMN IF NOT EXISTS shopify_js_checked_at timestamp without time zone
    """)
    cr.execute("""
        UPDATE sitemap_import_source
           SET shopify_js_mode = COALESCE(shopify_js_mode, 'auto'),
               shopify_js_status = COALESCE(shopify_js_status, 'unknown')
    """)
