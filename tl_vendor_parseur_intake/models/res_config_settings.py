# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    parseur_validate_vat_format = fields.Boolean(
        string="Validate NIF/VAT format",
        config_parameter="vendor_parseur_intake.validate_vat_format",
        default=True,
        help="Check Spanish NIF/CIF/NIE checksum and EU prefix/length.",
    )
    parseur_validate_vat_vies = fields.Boolean(
        string="Validate supplier VAT on VIES",
        config_parameter="vendor_parseur_intake.validate_vat_vies",
        default=False,
        help="Requires base_vat. Calls the EU VIES service (slower).",
    )
    parseur_hotkey_identify = fields.Char(
        string="Hotkey Identify",
        config_parameter="vendor_parseur_intake.hotkey_identify",
        default="F2",
    )
    parseur_hotkey_apply = fields.Char(
        string="Hotkey Apply",
        config_parameter="vendor_parseur_intake.hotkey_apply",
        default="F4",
    )
    parseur_hotkey_scan = fields.Char(
        string="Hotkey Process scan",
        config_parameter="vendor_parseur_intake.hotkey_scan",
        default="F7",
    )
    parseur_barcode_prefix = fields.Char(
        string="Scanner prefix to strip",
        config_parameter="vendor_parseur_intake.barcode_prefix",
        help="Characters the scanner sends before the code (AIM ID, ]C1, etc.).",
    )
    parseur_barcode_min_length = fields.Integer(
        string="Minimum barcode length",
        config_parameter="vendor_parseur_intake.barcode_min_length",
        default=3,
    )
    parseur_validate_qr = fields.Boolean(
        string="Validate QR payloads",
        config_parameter="vendor_parseur_intake.validate_qr",
        default=True,
    )
    parseur_qr_allowed_hosts = fields.Char(
        string="Allowed QR URL hosts",
        config_parameter="vendor_parseur_intake.qr_allowed_hosts",
        help="Comma-separated. Empty = any host.",
    )
    parseur_create_lots = fields.Boolean(
        string="Create missing lots on vendor receipts",
        config_parameter="vendor_parseur_intake.create_lots",
        default=True,
    )
    parseur_spellcheck = fields.Boolean(
        string="Spellcheck Parseur text against master data",
        config_parameter="vendor_parseur_intake.spellcheck",
        default=True,
        help="Correct vendor names, SKUs and descriptions toward unique Odoo matches.",
    )
    parseur_webhook_token = fields.Char(
        string='Parseur webhook token',
        config_parameter='vendor_parseur_intake.webhook_token',
        help='Sent by Parseur as header X-Webhook-Token or query parameter token.',
    )
    parseur_auto_apply = fields.Boolean(
        string='Auto-apply parsed documents',
        config_parameter='vendor_parseur_intake.auto_apply',
    )
    parseur_auto_validate_picking = fields.Boolean(
        string="Company-wide auto-validate (legacy)",
        config_parameter="vendor_parseur_intake.auto_validate_picking",
        help="Legacy company flag. Receipt validation is enabled per vendor "
        "on the contact form field Auto-validate Parseur receipts.",
    )
    parseur_over_policy = fields.Selection(
        [
            ('exception', 'Block over-receipt and extra products'),
            ('extend', 'Extend the PO with extra quantities / products'),
        ],
        string='Over-receipt policy',
        config_parameter='vendor_parseur_intake.over_policy',
        default='exception',
    )
    parseur_price_tolerance_pct = fields.Float(
        string='Price tolerance (%)',
        config_parameter='vendor_parseur_intake.price_tolerance_pct',
        default=2.0,
        help='Variance below this percentage is ignored (also bounded by the absolute tolerance).',
    )
    parseur_price_tolerance_abs = fields.Float(
        string='Price tolerance (absolute)',
        config_parameter='vendor_parseur_intake.price_tolerance_abs',
        default=0.05,
    )
    parseur_qty_tolerance_pct = fields.Float(
        string="Quantity tolerance (%)",
        config_parameter="vendor_parseur_intake.qty_tolerance_pct",
        default=0.0,
        help="Company default. Override per vendor on the partner form.",
    )
    parseur_qty_tolerance_abs = fields.Float(
        string="Quantity tolerance (units)",
        config_parameter="vendor_parseur_intake.qty_tolerance_abs",
        default=0.0,
    )
    parseur_price_diff_mode = fields.Selection(
        [
            ("rewrite_line", "Rewrite bill line unit price"),
            ("extra_line", "Keep PO price and add a difference line"),
        ],
        string="Price difference on the bill",
        config_parameter="vendor_parseur_intake.price_diff_mode",
        default="rewrite_line",
    )
    parseur_update_po_price = fields.Boolean(
        string='Update PO unit price when accepting the bill price',
        config_parameter='vendor_parseur_intake.update_po_price',
        help='Off by default: keep the original PO as the commercial agreement and only change the draft bill.',
    )
    parseur_auto_post_bill = fields.Boolean(
        string='Auto-post vendor bills after a clean match',
        config_parameter='vendor_parseur_intake.auto_post_bill',
        help='Posts the draft bill only if quantities were received, prices are decided and the total matches the document.',
    )
    parseur_bill_total_tolerance_pct = fields.Float(
        string='Bill total tolerance (%)',
        config_parameter='vendor_parseur_intake.bill_total_tolerance_pct',
        default=1.0,
    )
    parseur_bill_total_tolerance_abs = fields.Float(
        string='Bill total tolerance (absolute)',
        config_parameter='vendor_parseur_intake.bill_total_tolerance_abs',
        default=0.05,
    )
