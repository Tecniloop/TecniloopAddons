# -*- coding: utf-8 -*-
"""Create queue tracking columns before the 1.79 registry is initialized."""


def migrate(cr, version):
    # These columns were introduced by 19.0.1.78.0. Creating them explicitly
    # makes upgrades safe even if the 1.78 code was deployed before running -u.
    cr.execute("""
        ALTER TABLE sitemap_product_staging
        ADD COLUMN IF NOT EXISTS preview_job_uuid varchar
    """)
    cr.execute("""
        ALTER TABLE sitemap_product_staging
        ADD COLUMN IF NOT EXISTS import_job_uuid varchar
    """)
    cr.execute("""
        ALTER TABLE sitemap_product_staging
        ADD COLUMN IF NOT EXISTS last_job_date timestamp without time zone
    """)
    cr.execute("""
        ALTER TABLE sitemap_import_batch
        ADD COLUMN IF NOT EXISTS collect_job_uuid varchar
    """)
    cr.execute("""
        CREATE INDEX IF NOT EXISTS sitemap_product_staging_preview_job_uuid_idx
        ON sitemap_product_staging (preview_job_uuid)
        WHERE preview_job_uuid IS NOT NULL
    """)
    cr.execute("""
        CREATE INDEX IF NOT EXISTS sitemap_product_staging_import_job_uuid_idx
        ON sitemap_product_staging (import_job_uuid)
        WHERE import_job_uuid IS NOT NULL
    """)
