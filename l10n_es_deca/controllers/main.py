# Copyright 2026 Ecmr DeCA contributors
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import base64
import hashlib
import hmac
import logging
import re
from datetime import timedelta

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
        """Return the sealed PDF directly, as required for roadside inspection.

        ``sudo`` is intentional and narrowly scoped to an unguessable 256-bit token.
        The response exposes only the already-sealed PDF; no partner, chatter or
        mutable record data are serialized.  A landing page or login redirect would
        violate section three of the 5 June 2026 Resolution.
        """
        if not TOKEN_PATTERN.fullmatch(token):
            raise NotFound()
        version = (
            request.env["l10n.es.deca.version"]
            .sudo()
            .search([("access_token", "=", token)], limit=1)
        )
        if not version or not version.pdf_data:
            raise NotFound()

        now = fields.Datetime.now()
        public_until = version.public_until
        if version.document_id.actual_end_at:
            public_until = max(
                public_until,
                version.document_id.actual_end_at + timedelta(days=7),
            )
        if (
            public_until
            and now > public_until
            and version.document_id.state not in ("issued", "in_transit")
        ):
            raise Gone()

        pdf = base64.b64decode(version.pdf_data)
        actual_hash = hashlib.sha256(pdf).hexdigest()
        if not hmac.compare_digest(actual_hash, version.pdf_sha256 or ""):
            # Never serve bytes that no longer match the transactionally sealed hash.
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
