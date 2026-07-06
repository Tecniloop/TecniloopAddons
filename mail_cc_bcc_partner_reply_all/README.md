# Mail CC/BCC Partners Reply-All

Bridge module for Odoo 19.0 + OCA `mail_composer_cc_bcc`.

## Purpose

Odoo core keeps incoming CC addresses as raw strings in `mail.message.incoming_email_cc` and does not create `res.partner` records for unknown CC addresses.  The OCA module `mail_composer_cc_bcc` sends CC/BCC through partner fields.  This bridge creates partners for incoming CC addresses and stores them in the OCA CC field so replies can reuse the standard OCA composer logic.

## Behavior

- Incoming email CC addresses are found or created as `res.partner` records.
- Auto-created contacts are flagged with `mail_cc_bcc_auto_created`.
- The created/found CC partners are stored on `mail.message.recipient_cc_ids`.
- Reply composers prefill OCA `partner_cc_ids` from the parent message CC recipients.
- Historical messages received before this module was installed can still populate CC from raw `incoming_email_cc` when replying.
- CC/BCC partners are removed from normal `To` partners to avoid duplicated recipients.
- The chatter recipient popover displays OCA CC recipients, and BCC recipients for internal users only.

## Important note about incoming BCC

Incoming BCC recipients normally cannot be recovered from a received email because BCC is deliberately not delivered as a normal visible header.  This module supports OCA BCC partners for Odoo-sent messages and displays them internally when stored, but it cannot magically reconstruct unknown incoming BCC addresses if the mail server did not provide them.

## Dependencies

Install `mail_composer_cc_bcc` first.

## Installation

Copy this directory to an Odoo addons path, update the apps list, then install `Mail CC/BCC Partners Reply-All`.

For command-line update:

```bash
./odoo-bin -d <database> -u mail_cc_bcc_partner_reply_all --stop-after-init
```
