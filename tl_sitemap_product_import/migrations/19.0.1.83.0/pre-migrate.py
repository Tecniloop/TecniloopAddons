# -*- coding: utf-8 -*-


def migrate(cr, version):
    cr.execute("""
        ALTER TABLE sitemap_import_source
        ADD COLUMN IF NOT EXISTS numeric_scan_start varchar DEFAULT '00700'
    """)
    cr.execute("""
        ALTER TABLE sitemap_import_source
        ADD COLUMN IF NOT EXISTS numeric_scan_end varchar DEFAULT '40000'
    """)
    cr.execute("""
        ALTER TABLE sitemap_import_source
        ADD COLUMN IF NOT EXISTS numeric_scan_block_size integer DEFAULT 250
    """)
    cr.execute("""
        ALTER TABLE sitemap_import_source
        ADD COLUMN IF NOT EXISTS numeric_scan_last_article integer DEFAULT 0
    """)
    cr.execute("""
        ALTER TABLE sitemap_import_source
        ADD COLUMN IF NOT EXISTS numeric_scan_resume boolean DEFAULT FALSE
    """)
    cr.execute("""
        UPDATE sitemap_import_source
           SET numeric_scan_start = COALESCE(numeric_scan_start, '00700'),
               numeric_scan_end = COALESCE(numeric_scan_end, '40000'),
               numeric_scan_block_size = COALESCE(numeric_scan_block_size, 250),
               numeric_scan_last_article = COALESCE(numeric_scan_last_article, 0),
               numeric_scan_resume = COALESCE(numeric_scan_resume, FALSE)
    """)
