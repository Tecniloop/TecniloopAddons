# -*- coding: utf-8 -*-
import hmac
import json
import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class ParseurWebhookController(http.Controller):

    @http.route(
        [
            "/parseur/vendor/intake",
            "/parseur/vendor/intake/<string:mailbox_code>",
        ],
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
        save_session=False,
    )
    def parseur_vendor_intake(self, mailbox_code=None, **kwargs):
        try:
            raw = request.httprequest.get_data(as_text=True) or "{}"
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            payload = dict(kwargs)

        if not isinstance(payload, dict):
            return request.make_json_response(
                {"ok": False, "error": "invalid payload"}, status=400
            )

        mailbox = request.env["vendor.parseur.mailbox"].sudo()._from_request(
            code=mailbox_code, payload=payload
        )
        token_expected = ""
        if mailbox and mailbox.webhook_token:
            token_expected = mailbox.webhook_token
        else:
            token_expected = request.env["ir.config_parameter"].sudo().get_param(
                "vendor_parseur_intake.webhook_token", default=""
            ) or ""
        token_received = (
            request.httprequest.headers.get("X-Webhook-Token")
            or request.httprequest.headers.get("X-Parseur-Token")
            or kwargs.get("token")
            or request.httprequest.args.get("token")
            or payload.get("token")
            or ""
        )
        if token_expected and not hmac.compare_digest(
            str(token_received), str(token_expected)
        ):
            return request.make_json_response(
                {"ok": False, "error": "unauthorized"}, status=401
            )

        try:
            intake = request.env["vendor.document.intake"].sudo().ingest_parseur_payload(
                payload, mailbox=mailbox
            )
        except Exception:
            _logger.exception("Parseur vendor intake failed")
            return request.make_json_response(
                {"ok": False, "error": "processing failed"}, status=500
            )

        return request.make_json_response(
            {
                "ok": True,
                "intake_id": intake.id,
                "intake_name": intake.name,
                "state": intake.state,
                "document_type": intake.document_type,
                "mailbox": mailbox.code if mailbox else False,
                "purchase_id": intake.purchase_id.id or False,
                "picking_id": intake.picking_id.id or False,
                "invoice_id": intake.invoice_id.id or False,
                "exception_reason": intake.exception_reason or False,
            }
        )
