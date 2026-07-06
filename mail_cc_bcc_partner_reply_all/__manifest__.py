{
    "name": "Mail CC/BCC Partners Reply-All",
    "summary": "Create incoming CC partners and reuse OCA CC/BCC recipients in replies",
    "version": "19.0.1.0.0",
    "category": "Discuss",
    "license": "AGPL-3",
    "author": "OpenAI, Odoo Community Association (OCA)",
    "website": "https://github.com/OCA/social",
    "depends": ["mail_composer_cc_bcc"],
    "data": [],
    "assets": {
        "mail.assets_core": [
            "mail_cc_bcc_partner_reply_all/static/src/core/common/message_model_patch.js",
            "mail_cc_bcc_partner_reply_all/static/src/core/common/message.xml",
            "mail_cc_bcc_partner_reply_all/static/src/core/common/message_notification_popover.xml",
        ],
    },
    "installable": True,
    "application": False,
}
