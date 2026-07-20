# -*- coding: utf-8 -*-
"""Crea explícitamente las columnas técnicas de variantes al actualizar."""


def migrate(cr, version):
    cr.execute("""
        ALTER TABLE product_product
        ADD COLUMN IF NOT EXISTS sitemap_source_variant_id varchar
    """)
    cr.execute("""
        ALTER TABLE product_product
        ADD COLUMN IF NOT EXISTS sitemap_variant_available boolean DEFAULT true
    """)
    cr.execute("""
        CREATE INDEX IF NOT EXISTS product_product_sitemap_source_variant_id_idx
        ON product_product (sitemap_source_variant_id)
    """)
