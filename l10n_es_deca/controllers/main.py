# Copyright 2026 Ecmr DeCA contributors
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import base64
import hashlib
import hmac
import logging
import re

from odoo import fields, http
from odoo.http import request
from werkzeug.exceptions import Gone, InternalServerError, NotFound


TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{43}$")
_logger = logging.getLogger(__name__)


class DecaPublicController(http.Controller):
    @http.route(
        "/deca/pdf/<string:token>",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
        save_session=False,
    )
    def download_deca_pdf(self, token, **_kwargs):
        """Return the current sealed PDF through the document's stable Method-A URL."""
        if not TOKEN_PATTERN.fullmatch(token):
            raise NotFound()
        document = (
            request.env["l10n.es.deca.document"]
            .sudo()
            .search([("public_access_token", "=", token)], limit=1)
        )
        if not document or not document.current_version_id.pdf_data:
            raise NotFound()

        now = fields.Datetime.now()
        if (
            not document.public_access_active
            or (
                document.public_access_until
                and now > document.public_access_until
                and document.state not in ("issued", "in_transit")
            )
        ):
            document._close_public_access_if_expired(now=now)
            raise Gone()

        version = document.current_version_id
        pdf = base64.b64decode(version.pdf_data)
        actual_hash = hashlib.sha256(pdf).hexdigest()
        if not hmac.compare_digest(actual_hash, version.pdf_sha256 or ""):
            _logger.error("DeCA PDF integrity check failed for version %s", version.id)
            raise InternalServerError()
        headers = [
            ("Content-Type", "application/pdf"),
            ("Content-Length", str(len(pdf))),
            ("Content-Disposition", f'attachment; filename="{version.pdf_filename}"'),
            ("Cache-Control", "private, no-store, max-age=0"),
            ("Pragma", "no-cache"),
            ("X-Content-Type-Options", "nosniff"),
            ("Content-Security-Policy", "default-src 'none'; sandbox"),
        ]
        return request.make_response(pdf, headers=headers)
