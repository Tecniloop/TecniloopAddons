# Copyright 2026 Ecmr DeCA contributors
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    deca_default_purpose = fields.Selection(
        [
            ("administrative", "Administrative only (no signature)"),
            ("contractual", "Administrative and contractual (PAdES required)"),
        ],
        string="Default DeCA purpose",
        required=True,
        default="administrative",
        help=(
            "Applied to new DeCA drafts for this operational company. "
            "Administrative drafts are not signed. Contractual drafts must be "
            "signed according to the default party policy before they can be issued."
        ),
    )
    deca_default_signature_party_policy = fields.Selection(
        [
            ("shipper", "Contractual shipper"),
            ("carrier", "Effective carrier"),
            ("both", "Contractual shipper and effective carrier"),
        ],
        string="Default DeCA signature parties",
        required=True,
        default="both",
        help=(
            "Parties preselected on new DeCA drafts. This policy is enforced only "
            "when the document purpose is administrative and contractual."
        ),
    )
    deca_default_shipper_signing_company_id = fields.Many2one(
        "res.company",
        string="Default shipper signing company",
        help=(
            "Company preselected to sign for the contractual shipper. Its "
            "commercial partner must match the shipper on the DeCA."
        ),
    )
    deca_default_carrier_signing_company_id = fields.Many2one(
        "res.company",
        string="Default carrier signing company",
        help=(
            "Company preselected to sign for the effective carrier. Its commercial "
            "partner must match the carrier on the DeCA."
        ),
    )

    deca_ades_profile = fields.Selection(
        [
            ("pades_b_b", "PAdES B-B"),
            ("pades_b_t", "PAdES B-T with trusted timestamp"),
        ],
        string="DeCA signature profile",
        required=True,
        default="pades_b_t",
        help=(
            "PAdES B-T embeds an RFC 3161 timestamp. Certificate trust, identity, "
            "revocation and AdES/QES legal qualification still require an "
            "independent validation policy."
        ),
    )
    deca_ades_tsa_url = fields.Char(
        string="DeCA timestamp authority URL",
        help="HTTPS endpoint of the RFC 3161 timestamp authority used for PAdES B-T.",
    )


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    deca_default_purpose = fields.Selection(
        related="company_id.deca_default_purpose", readonly=False
    )
    deca_default_signature_party_policy = fields.Selection(
        related="company_id.deca_default_signature_party_policy", readonly=False
    )
    deca_default_shipper_signing_company_id = fields.Many2one(
        related="company_id.deca_default_shipper_signing_company_id", readonly=False
    )
    deca_default_carrier_signing_company_id = fields.Many2one(
        related="company_id.deca_default_carrier_signing_company_id", readonly=False
    )

    deca_ades_profile = fields.Selection(
        related="company_id.deca_ades_profile", readonly=False
    )
    deca_ades_tsa_url = fields.Char(
        related="company_id.deca_ades_tsa_url", readonly=False
    )
