# -*- coding: utf-8 -*-


def migrate(cr, version):
    cr.execute("""
        ALTER TABLE sitemap_product_staging
        ADD COLUMN IF NOT EXISTS attachment_urls_json text
    """)
    cr.execute("""
        ALTER TABLE sitemap_product_staging
        ADD COLUMN IF NOT EXISTS attachment_count integer DEFAULT 0
    """)
    cr.execute("""
        ALTER TABLE sitemap_import_source
        ADD COLUMN IF NOT EXISTS import_attachments boolean DEFAULT true
    """)
    cr.execute("""
        ALTER TABLE sitemap_import_source
        ADD COLUMN IF NOT EXISTS max_attachments_per_product integer DEFAULT 20
    """)
    cr.execute("""
        ALTER TABLE ir_attachment
        ADD COLUMN IF NOT EXISTS sitemap_source_url varchar
    """)
    cr.execute("""
        ALTER TABLE ir_attachment
        ADD COLUMN IF NOT EXISTS sitemap_sha256 varchar
    """)
    cr.execute("""
        ALTER TABLE ir_attachment
        ADD COLUMN IF NOT EXISTS sitemap_document_type varchar
    """)
    cr.execute("""
        ALTER TABLE ir_attachment
        ADD COLUMN IF NOT EXISTS sitemap_imported boolean DEFAULT false
    """)
    cr.execute("""
        CREATE INDEX IF NOT EXISTS ir_attachment_sitemap_sha256_idx
        ON ir_attachment (sitemap_sha256)
        WHERE sitemap_sha256 IS NOT NULL
    """)
    cr.execute("""
        CREATE INDEX IF NOT EXISTS ir_attachment_sitemap_source_url_idx
        ON ir_attachment (sitemap_source_url)
        WHERE sitemap_source_url IS NOT NULL
    """)
