/* Copyright 2016 David Gómez...
   Copyright 2025 Alia Technologies - César Parguiñas
   License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
*/

import { PosOrder } from "@point_of_sale/app/models/pos_order";
import { patch } from "@web/core/utils/patch";

patch(PosOrder.prototype, {
    setup(vals) {
        super.setup(...arguments);
        this.l10n_es_unique_id = vals.l10n_es_unique_id || false;
        this.l10n_es_simplified_number = vals.l10n_es_simplified_number || 0;
        this.is_l10n_es_simplified_invoice = vals.is_l10n_es_simplified_invoice || false;
    },

    serializeForORM(opts = {}) {
        const res = super.serializeForORM(...arguments);
        if (!this.isToInvoice()) {
            res.l10n_es_unique_id = this.l10n_es_unique_id || false;
            res.l10n_es_simplified_number = this.l10n_es_simplified_number || 0;
            res.is_l10n_es_simplified_invoice = !!this.is_l10n_es_simplified_invoice;
        }
        return res;
    },

    get_l10n_es_unique_id() {
        return this.l10n_es_unique_id || "";
    },
});
