import {DynamicRecordList} from "@web/model/relational_model/dynamic_record_list";
import {listView} from "@web/views/list/list_view";

export class MailMessageUpdateListModel extends listView.Model {
    async _loadData(config) {
        const resIds =
            this.action &&
            this.action.currentController &&
            this.action.currentController.props.resIds;
        if ((!config.context.first_id || !config.context.last_id) && resIds) {
            if (resIds.length > 0) {
                config.context = {
                    ...config.context,
                    first_id: resIds[resIds.length - 1],
                    last_back_id: resIds[0],
                };
            }
        }
        return super._loadData(...arguments);
    }
}

export class MailMessageDynamicRecordList extends DynamicRecordList {
    setup() {
        super.setup(...arguments);
        this.lastOffset = 0;
    }

    async _load(offset, limit, orderBy, domain) {
        const rec_len = this.records.length;
        if (this.resModel === "mail.message" && rec_len > 0) {
            const firstId = this.records[0].resId;
            const lastId = this.records[rec_len - 1].resId;
            this.config.context = {
                ...this.config.context,
                first_id: firstId,
                last_id: lastId,
                last_offset: this.lastOffset,
                list_count: this.count,
            };
        }
        return await super._load(offset, limit, orderBy, domain);
    }

    _setData(data) {
        super._setData(data);
        this.lastOffset = this.offset;
    }
}

MailMessageUpdateListModel.DynamicRecordList = MailMessageDynamicRecordList;
