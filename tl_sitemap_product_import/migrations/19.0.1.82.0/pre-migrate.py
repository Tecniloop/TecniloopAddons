# -*- coding: utf-8 -*-


def migrate(cr, version):
    cr.execute("""
        ALTER TABLE sitemap_import_batch
        ADD COLUMN IF NOT EXISTS numeric_scan_total_blocks integer DEFAULT 0
    """)
    cr.execute("""
        ALTER TABLE sitemap_import_batch
        ADD COLUMN IF NOT EXISTS numeric_scan_completed_blocks integer DEFAULT 0
    """)
    cr.execute("""
        ALTER TABLE sitemap_import_batch
        ADD COLUMN IF NOT EXISTS numeric_scan_found_count integer DEFAULT 0
    """)
