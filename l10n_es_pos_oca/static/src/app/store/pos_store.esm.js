/* Copyright 2016 David Gómez Quilón <david.gomez@aselcis.com>
   Copyright 2018-19 Tecnativa - David Vidal
   Copyright 2024 (APSL-Nagarro) - Antoni Marroig
   Copyright 2025 Alia Technologies - César Parguiñas
   License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
*/

import { ConnectionLostError } from "@web/core/network/rpc";
import { PosStore } from "@point_of_sale/app/services/pos_store";
import { patch } from "@web/core/utils/patch";

patch(PosStore.prototype, {
    /**
     * Gets the padded simplified invoice number.
     * @param {Number} number
     * @param {Number} padding
     * @returns {String}
     * @private
     */
    _getPaddingSimpleInv(number, padding) {
        const numberString = String(number || 0);
        const diff = padding - numberString.length;
        if (diff <= 0) {
            return numberString;
        }
        return `${"0".repeat(diff)}${numberString}`;
    },

    /**
     * Sets the simplified invoice number in the config.
     * @param {Number} l10n_es_simplified_invoice_number
     */
    setSimplifiedInvoiceNumber(l10n_es_simplified_invoice_number) {
        this.config.l10n_es_simplified_invoice_number = l10n_es_simplified_invoice_number;
    },

    /**
     * Gets the current simplified invoice number from the config.
     * @returns {Number}
     */
    getCurrentSimplifiedInvoiceNumber() {
        return this.config.l10n_es_simplified_invoice_number;
    },

    /**
     * Generates the simplified unique ID for the current invoice.
     * @returns {String}
     */
    getSimplifiedUniqueId() {
        return `${this.config.l10n_es_simplified_invoice_prefix || ""}${this._getPaddingSimpleInv(
            this.config.l10n_es_simplified_invoice_number,
            this.config.l10n_es_simplified_invoice_padding || 0
        )}`;
    },

    /**
     * Increments the simplified invoice number in the config.
     */
    incrementSimplifiedInvoiceNumber() {
        this.config.l10n_es_simplified_invoice_number += 1;
    },

    /**
     * Checks if there are pending orders to be synced.
     * @returns {Boolean}
     */
    hasPendingOrders() {
        const { orderToCreate, orderToUpdate } = this.getPendingOrder();
        return orderToCreate.length + orderToUpdate.length > 0;
    },

    /**
     * Gets the next simplified invoice number, taking into account pending orders.
     * @returns {Promise<Number>}
     */
    async getSimpleInvNextNumber() {
        // First, get the next number from the DB to be sure we have the latest.
        try {
            const config = await this.data.searchRead(
                "pos.config",
                [["id", "=", this.config.id]],
                ["l10n_es_simplified_invoice_number"]
            );
            this.config.l10n_es_simplified_invoice_number =
                config[0]?.l10n_es_simplified_invoice_number || 1;
        } catch (error) {
            // Throw error if it's a connection lost error and we want to prevent offline validation.
            if (error instanceof ConnectionLostError && this.config.prevent_offline_validation) {
                throw error;
            }
            // Offline and no pending orders: increment from the local cached number.
            if (!this.hasPendingOrders()) {
                this.incrementSimplifiedInvoiceNumber();
            }
            console.error(error);
        }

        if (this.hasPendingOrders()) {
            const { orderToCreate } = this.getPendingOrder();
            const simplifiedNumbers = orderToCreate
                .map((order) => order.l10n_es_simplified_number)
                .filter((number) => Number.isFinite(number) && number > 0);

            // Prevent overlapping by calculating the max number in pending orders when lost connection.
            if (simplifiedNumbers.length) {
                const simplifiedInvNumFromOrderPending = Math.max(...simplifiedNumbers) + 1;
                if (
                    this.config.l10n_es_simplified_invoice_number <
                    simplifiedInvNumFromOrderPending
                ) {
                    this.config.l10n_es_simplified_invoice_number =
                        simplifiedInvNumFromOrderPending;
                }
            }

            return Promise.reject(new ConnectionLostError());
        }

        return this.config.l10n_es_simplified_invoice_number;
    },
});
