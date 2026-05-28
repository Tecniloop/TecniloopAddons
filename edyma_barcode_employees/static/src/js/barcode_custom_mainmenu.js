/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { registry } from "@web/core/registry";
import { MainMenu } from "@stock_barcode/main_menu/main_menu";

patch(MainMenu.prototype, {
    setup() {
        super.setup();
        this.employeeName = this._getStoredEmployeeName();
    },

    _getStoredEmployeeName() {
        return localStorage.getItem('employeeName') || 'Nombre no encontrado';
    },
});
