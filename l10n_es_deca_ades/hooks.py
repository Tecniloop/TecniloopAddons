# Copyright 2026 Ecmr DeCA contributors
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import sys
from importlib import metadata

from odoo import _
from odoo.exceptions import UserError


def pre_init_hook(env):
    """Reject dependency combinations that conflict with Odoo 19 core pins.

    Odoo 19 pins ``cryptography==3.4.8`` below Python 3.12, while pyHanko 0.24
    requires ``cryptography>=42.0.1``. On Python 3.12, Odoo pins 42.0.8 and the
    two dependency graphs are compatible. The narrow pyHanko series guard keeps
    later releases from silently upgrading Odoo's cryptography/lxml stack.
    """
    del env
    if sys.version_info < (3, 12):
        raise UserError(
            _(
                "l10n_es_deca_ades requires Odoo 19 on Python 3.12 or newer. "
                "Use an external signing service on older Python runtimes."
            )
        )
    pyhanko_version = metadata.version("pyHanko")
    if not pyhanko_version.startswith("0.24."):
        raise UserError(
            _(
                "l10n_es_deca_ades requires pyHanko 0.24.x to remain compatible "
                "with the official Odoo 19 dependency pins."
            )
        )
