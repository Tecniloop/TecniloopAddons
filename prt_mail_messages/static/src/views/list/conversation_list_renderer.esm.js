import {ConversationReview} from "../../components/conversation_review.esm";
import {ListRenderer} from "@web/views/list/list_renderer";

export class ConversationUpdateListRenderer extends ListRenderer {
    static template = "prt_mail_messages.ListRenderer";
    static recordRowTemplate = "prt_mail_messages.Conversation.ListRenderer.RecordRow";
    static components = {
        ...ListRenderer.components,
        ConversationReview,
    };
}
