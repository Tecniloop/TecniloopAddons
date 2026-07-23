# Copyright 2026 Tecniloop
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
from odoo import _
from odoo.exceptions import UserError


class SuenlaceImportError(UserError):
    """Error de negocio durante la importación de un fichero SUENLACE."""


def missing_journal(journal_type):
    return SuenlaceImportError(
        _("No hay ningún diario de tipo '%s' configurado en la compañía.")
        % journal_type
    )
