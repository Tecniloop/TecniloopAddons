/* Copyright 2016 David Gómez Quilón <david.gomez@aselcis.com>
   Copyright 2018 Tecnativa - David Vidal
   Copyright 2020 Tecnativa - João Marques
   Copyright 2024 (APSL-Nagarro) - Antoni Marroig
   Copyright 2025 Alia Technologies - César Parguiñas
   License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
*/

import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { ConnectionLostError } from "@web/core/network/rpc";
import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";

patch(PaymentScreen.prototype, {
    /**
     * Validates the order, setting simplified invoice numbers if applicable.
     * @override
     * @param {Boolean} isForceValidate
     * @returns {Promise<void|Boolean>}
     */
    async validateOrder(isForceValidate = false) {
        const belowLimit =
            this.currentOrder.priceIncl <= this.pos.config.l10n_es_simplified_invoice_limit;

        if (this.pos.config.is_simplified_config) {
            const order = this.currentOrder;
            if (belowLimit && !order.isToInvoice()) {
                try {
                    await this.setSimpleInvNumber();
                } catch (error) {
                    if (error instanceof ConnectionLostError && this.pos.config.prevent_offline_validation) {
                        this.dialog.add(AlertDialog, {
                            title: _t("Connection Lost"),
                            body: _t(
                                "Cannot validate the order without connection. This may be due to a lost connection or the server being unreachable at this moment. Please reconnect and try again."
                            ),
                            confirmLabel: _t("Ok"),
                        });
                        return false;
                    }
                }
            } else {
                // Force full invoice above the legal simplified-invoice limit. Online is needed.
                order.setToInvoice(true);
            }
        }
        await super.validateOrder(isForceValidate);
    },

    /**
     * Sets the simplified invoice number for the current order.
     * @returns {Promise<void>}
     */
    async setSimpleInvNumber() {
        try {
            const l10nEsSimplifiedInvoiceNumber = await this.pos.getSimpleInvNextNumber();
            this.pos.setSimplifiedInvoiceNumber(l10nEsSimplifiedInvoiceNumber);
        } catch (error) {
            if (error instanceof ConnectionLostError) {
                throw error;
            }
        } finally {
            const order = this.currentOrder;
            order.update({
                l10n_es_simplified_number: this.pos.getCurrentSimplifiedInvoiceNumber(),
                l10n_es_unique_id: this.pos.getSimplifiedUniqueId(),
                is_l10n_es_simplified_invoice: true,
            });
        }
    },
});
