import { _t } from "@web/core/l10n/translation";
import { parseFloat } from "@web/views/fields/parsers";
import { NumberPopup } from "@point_of_sale/app/components/popups/number_popup/number_popup";
import { SelectionPopup } from "@point_of_sale/app/components/popups/selection_popup/selection_popup";
import { makeAwaitable } from "@point_of_sale/app/utils/make_awaitable_dialog";
import { ControlButtons } from "@point_of_sale/app/screens/product_screen/control_buttons/control_buttons";
import { patch } from "@web/core/utils/patch";

function parseDiscount(value) {
    return typeof value === "number" ? value : isNaN(parseFloat(value)) ? 0 : parseFloat("" + value);
}

patch(ControlButtons.prototype, {
    async onClickTripleDiscount() {
        const line = this.currentOrder?.getSelectedOrderline();
        if (!line) {
            this.notification.add(_t("Select a line first."));
            return;
        }

        const discountingType = await this._askDiscountingType(
            line.discounting_type || "multiplicative"
        );
        if (!discountingType) {
            return;
        }
        const d1 = await this._askTripleDiscountValue(_t("Discount 1 (%)"), line.discount || 0);
        if (d1 === null) {
            return;
        }
        const d2 = await this._askTripleDiscountValue(_t("Discount 2 (%)"), line.discount2 || 0);
        if (d2 === null) {
            return;
        }
        const d3 = await this._askTripleDiscountValue(_t("Discount 3 (%)"), line.discount3 || 0);
        if (d3 === null) {
            return;
        }

        line.setDiscountingType(discountingType);
        line.setDiscount(d1);
        line.setDiscount2(d2);
        line.setDiscount3(d3);
    },

    async _askDiscountingType(currentValue) {
        return await makeAwaitable(this.dialog, SelectionPopup, {
            title: _t("Discounting type"),
            list: [
                {
                    id: "multiplicative",
                    label: _t("Multiplicative"),
                    item: "multiplicative",
                    isSelected: currentValue === "multiplicative",
                },
                {
                    id: "additive",
                    label: _t("Additive"),
                    item: "additive",
                    isSelected: currentValue === "additive",
                },
            ],
        });
    },

    async _askTripleDiscountValue(title, currentValue) {
        const payload = await makeAwaitable(this.dialog, NumberPopup, {
            title,
            subtitle: _t("Current value: %s%%", currentValue),
            confirmButtonLabel: _t("Apply"),
        });
        return payload === undefined || payload === null || payload === false ? null : parseDiscount(payload);
    },
});
