/** @odoo-module **/
import { ActivityMenu } from "@hr_attendance/components/attendance_menu/attendance_menu";
import { isIosApp } from "@web/core/browser/feature_detection";
import { patch } from "@web/core/utils/patch";
import { rpc } from "@web/core/network/rpc";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";

patch(ActivityMenu.prototype, {
    setup() {
        this.orm = useService("orm");
        super.setup();
    },

    async searchReadEmployee() {
        // Llamamos al método original para obtener los datos básicos (ID, estado de fichaje, etc.)
        await super.searchReadEmployee();

        // El saldo de la bolsa de horas ya viene incluido en 'this.employee' gracias 
        // a nuestra modificación en el controlador Python (main.py).
        // De esta forma evitamos hacer un orm.read adicional que fallaría por permisos.
        if (this.employee && this.employee.id) {
            this.state.negative_hours_balance = this.employee.overtime_balance_display || false;
            this.state.overtime_balance = this.employee.overtime_balance || 0.0;
        }
    },

    async customCheckIn(work_location, extra_hours_required = false) {

        this.dropdown.close();

        if (isIosApp()) {
            await rpc("/tl_attendance_extra/custom_check_in_out", {
                // CHANGE: Añadir los valores de los botones
                work_location: work_location,
                extra_hours_required: extra_hours_required
            });
        } else {
            // Note: searchReadEmployee is called here, but it's the original one since we removed our patch
            await this.searchReadEmployee()
            navigator.geolocation.getCurrentPosition(
                async ({ coords: { latitude, longitude } }) => {
                    await rpc("/tl_attendance_extra/custom_check_in_out", {
                        latitude,
                        longitude,
                        work_location: work_location,
                        extra_hours_required: extra_hours_required
                    });
                    await this.searchReadEmployee();
                },
                async () => {
                    await rpc("/tl_attendance_extra/custom_check_in_out", {
                        work_location: work_location,
                        extra_hours_required: extra_hours_required
                    });
                    await this.searchReadEmployee();
                },
                {
                    enableHighAccuracy: true,
                }
            );
        }
    }
});
