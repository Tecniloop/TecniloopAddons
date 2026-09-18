# Copyright 2026 Ecmr DeCA contributors
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).


def migrate(cr, version):
    # Reuse the token/URL already carried by the current public PDF so QR codes
    # distributed before the upgrade remain valid under Method A.
    cr.execute(
        """
        UPDATE l10n_es_deca_document d
           SET public_access_token = v.access_token,
               public_url = v.public_url,
               public_access_active = TRUE
          FROM l10n_es_deca_version v
         WHERE d.current_version_id = v.id
           AND d.public_access_token IS NULL
        """
    )

    # The old schema required one unique token per immutable version. Method A
    # deliberately reuses the document token across all future versions. Drop
    # any unique constraint whose sole constrained column is access_token.
    cr.execute(
        """
        SELECT con.conname
          FROM pg_constraint con
          JOIN pg_class rel ON rel.oid = con.conrelid
          JOIN pg_namespace nsp ON nsp.oid = rel.relnamespace
         WHERE rel.relname = 'l10n_es_deca_version'
           AND con.contype = 'u'
           AND (
               SELECT array_agg(att.attname ORDER BY u.ord)
                 FROM unnest(con.conkey) WITH ORDINALITY AS u(attnum, ord)
                 JOIN pg_attribute att
                   ON att.attrelid = rel.oid AND att.attnum = u.attnum
           ) = ARRAY['access_token']::name[]
        """
    )
    for (constraint_name,) in cr.fetchall():
        cr.execute(
            'ALTER TABLE l10n_es_deca_version DROP CONSTRAINT "%s"'
            % constraint_name.replace('"', '""')
        )
