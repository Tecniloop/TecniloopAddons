/** @odoo-module **/

import { onWillUnmount } from "@odoo/owl";
import { FormController } from "@web/views/form/form_controller";
import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";

const DEFAULTS = {
    identify: "F2",
    apply: "F4",
    scan: "F7",
};

patch(FormController.prototype, {
    setup() {
        super.setup(...arguments);
        this._tlOrm = useService("orm");
        if (this.props.resModel === "vendor.document.intake") {
            this._tlOnKey = this._tlHandleIntakeKey.bind(this);
            document.addEventListener("keydown", this._tlOnKey);
            onWillUnmount(() => {
                if (this._tlOnKey) {
                    document.removeEventListener("keydown", this._tlOnKey);
                }
            });
        }
    },
    _tlHotkeys() {
        return DEFAULTS;
    },
    async _tlHandleIntakeKey(ev) {
        if (this.props.resModel !== "vendor.document.intake") {
            return;
        }
        const keys = this._tlHotkeys();
        const mapping = {
            [keys.identify]: "action_identify",
            [keys.apply]: "action_apply",
            [keys.scan]: "action_process_scanned_barcode",
        };
        const method = mapping[ev.key];
        if (!method) {
            return;
        }
        const resId = this.model?.config?.resId;
        if (!resId) {
            return;
        }
        ev.preventDefault();
        ev.stopPropagation();
        await this._tlOrm.call("vendor.document.intake", method, [[resId]]);
        if (this.model?.root?.load) {
            await this.model.root.load();
        }
    },
});
