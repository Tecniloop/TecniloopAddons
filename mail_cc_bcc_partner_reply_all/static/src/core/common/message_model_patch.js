/** @odoo-module **/

import { Message } from "@mail/core/common/message_model";
import { fields } from "@mail/core/common/record";
import { patch } from "@web/core/utils/patch";

patch(Message.prototype, {
    recipient_cc_ids: fields.Many("res.partner"),
    recipient_bcc_ids: fields.Many("res.partner"),
});
