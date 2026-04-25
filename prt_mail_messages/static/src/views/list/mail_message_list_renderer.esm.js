import {ListRenderer} from "@web/views/list/list_renderer";
import {MessageReview} from "../../components/message_review.esm";
import {onWillStart} from "@odoo/owl";
import {useService} from "@web/core/utils/hooks";

export class MailMessageUpdateListRenderer extends ListRenderer {
    static template = "prt_mail_messages.ListRenderer";
    static recordRowTemplate = "prt_mail_messages.Message.ListRenderer.RecordRow";
    static components = {
        ...ListRenderer.components,
        MessageReview,
    };

    setup() {
        super.setup();
        this.orm = useService("orm");
        this.note_color = "";
        onWillStart(this.onWillStart);
    }

    get hasActionsColumn() {
        return false;
    }

    async onWillStart() {
        this.note_color = await this.orm.call(
            "mail.message",
            "get_message_note_color",
            []
        );
    }
}
