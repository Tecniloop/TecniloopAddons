import {Component, useState} from "@odoo/owl";
import {_t} from "@web/core/l10n/translation";
import {useService} from "@web/core/utils/hooks";

export class MessageReview extends Component {
    static template = "prt_mail_messages.MessageReview";
    static props = ["record", "note_color"];

    setup() {
        super.setup();
        this.actionService = useService("action");
        this.state = useState({
            record: this.props.record.data,
            resId: this.props.record.resId,
            has_attachments: this.props.record.data.attachment_ids.resIds.length > 0,
        });
    }

    get table_class() {
        if (this.state.record.is_note) {
            let color = null;

            if (window.CSS === undefined) {
                color = this.props.note_color;
            } else {
                color = CSS.escape(this.props.note_color);
            }
            return `background-color: ${color}`;
        }
        return "";
    }

    get title() {
        if (this.state.record.is_note) {
            return _t("Internal Note");
        }
        return _t("Message");
    }

    get avatar() {
        if (this.state.record.author_avatar) {
            return `/web/image/mail.message/${encodeURIComponent(this.state.resId)}/author_avatar`;
        }
        return "/web/static/img/user_placeholder.jpg";
    }

    get delete_date() {
        if (this.state.record.deleted_days === 0) {
            return _t("Deleted less than one day ago");
        }
        return _t(`Deleted ${this.state.record.deleted_days} days ago`);
    }

    openRecordReference(ev) {
        ev.stopPropagation();
        const recordRef = this.state.record.record_ref;
        this.actionService.doAction({
            type: "ir.actions.act_window",
            views: [[false, "form"]],
            res_model: recordRef.resModel,
            res_id: recordRef.resId,
        });
    }
}
