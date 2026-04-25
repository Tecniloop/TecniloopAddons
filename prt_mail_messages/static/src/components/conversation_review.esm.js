import {Component, onWillStart, useState} from "@odoo/owl";
import {_t} from "@web/core/l10n/translation";
import {useService} from "@web/core/utils/hooks";

export class ConversationReview extends Component {
    static template = "prt_mail_messages.ConversationReview";
    static props = ["record"];

    setup() {
        super.setup();
        this.actionService = useService("action");
        this.orm = useService("orm");
        this.state = useState({
            record: this.props.record.data,
            resId: this.props.record.resId,
            conversation_message: {},
            participants: [],
        });
        onWillStart(this.onWillStart);
    }

    async onWillStart() {
        const result = await this.orm.call("mail.message", "search_read", [], {
            domain: [
                ["id", "in", this.state.record.message_ids.resIds],
                ["message_type", "!=", "notification"],
            ],
            fields: ["id", "author_id", "preview"],
        });
        if (result.length > 0) {
            this.state.conversation_message = result[0];
        }
        this.state.participants = await this.orm.call(
            "res.partner",
            "search_read",
            [],
            {
                domain: [["id", "in", this.state.record.partner_ids.resIds]],
                fields: ["id", "name"],
            }
        );
    }

    sanitizeName(name) {
        if (!name) {
            return "";
        }
        if (name.includes("@")) {
            return name.split("@")[0];
        }
        return name;
    }

    get avatar() {
        if (this.state.record.author_id) {
            return `/web/image/res.partner/${this.state.record.author_id[0]}/image_128`;
        }
        return "/web/static/img/user_placeholder.jpg";
    }

    get author() {
        if (this.state.record.author_id) {
            return this.state.record.author_id[1];
        }
        return "";
    }

    get title() {
        const author = this.state.record.author_id;
        if (author) {
            return this.sanitizeName(author[1]);
        }
        return "";
    }

    get messageAvatar() {
        const message = this.state.conversation_message;
        if (message.author_id && message.author_id[0]) {
            return `/web/image/res.partner/${message.author_id[0]}/image_128`;
        }
        return "/web/static/img/user_placeholder.jpg";
    }

    get messageAuthor() {
        const author = this.state.conversation_message.author_id;
        if (author) {
            return author[1];
        }
        return "";
    }

    get messageCount() {
        const count = this.state.record.message_count;
        if (count === 0) {
            return _t("No messages");
        }
        let messageCountText =
            count === 1 ? _t("%s message", count) : _t("%s messages", count);
        const messageNeedactionCount = this.state.record.message_needaction_count;
        if (messageNeedactionCount > 0) {
            messageCountText = _t(
                "%s (%s new)",
                messageCountText,
                messageNeedactionCount
            );
        }
        return messageCountText;
    }
}
