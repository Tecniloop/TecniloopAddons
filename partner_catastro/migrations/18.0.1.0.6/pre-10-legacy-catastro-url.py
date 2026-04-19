import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Create the legacy column if it is still missing on upgraded databases.

    Version 18.0.1.0.6 makes catastro_url a non-stored computed field so the
    column is no longer required, but creating it here keeps deployments safe
    if the previous code revision reached the server before the upgrade step.
    """
    cr.execute("ALTER TABLE res_partner ADD COLUMN IF NOT EXISTS catastro_url varchar")
    _logger.info('Ensured legacy column res_partner.catastro_url exists before upgrade')
