/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import BarcodeModel from '@stock_barcode/models/barcode_model';


patch(BarcodeModel.prototype, {
    async _validate() {
        const employeeName = localStorage.getItem('employeeName');

        if (!employeeName) {
            console.error("No se encontró el nombre del empleado en localStorage.");
            return;
        }

        let employeeId = null;
        try {
            const result = await this.orm.call('hr.employee', 'search_read', [
                [['name', '=', employeeName]],
                ['id']
            ]);
            if (result.length > 0) {
                this.validateContext = {
                    ...this.validateContext,
                    employee_id: result[0].id,
                };
            } else {
                console.error("No se encontró el ID del empleado en el servidor.");
                return;
            }
        } catch (error) {
            console.error("Error al buscar el ID del empleado:", error);
            return;
        }

        return await super._validate();
    },
});


//import { Component, useState } from "@odoo/owl";
//import { registry } from "@web/core/registry";
//import { useService } from "@web/core/utils/hooks";
//
//
//
//function getEmployees(orm) {
//    orm.call('/get_employees', {})
//        .then((response) => {
//            if (response) {
//                const employeeList = document.getElementById('employee-list');
//                employeeList.innerHTML = '';
//
//                for (const employee of response) {
//                    const listItem = document.createElement('li');
//                    listItem.textContent = `${employee.name} - ${employee.job_title}`;
//                    employeeList.appendChild(listItem);
//                }
//            } else {
//                console.error('Error al obtener la lista de empleados');
//            }
//        })
//        .catch((error) => {
//            console.error('Error:', error);
//        });
//    document.addEventListener('touchmove', function(event) {
//    }, { passive: true });
//}
//
//function listenAndShowMessage(actionService) {
//    const originalDoAction = actionService.doAction;
//
//    actionService.doAction = async function (action, options) {
//        if (action === "stock_barcode.stock_barcode_action_main_menu") {
//            showEmployeeMessage();
//        }
//        return originalDoAction.apply(this, arguments);
//    };
//
//    function showEmployeeMessage() {
//        const employeeName = localStorage.getItem("employeeName") || "Empleado";
//        const mainMenuElement = document.querySelector(".o_stock_barcode_main_menu");
//
//        if (!mainMenuElement) {
//            console.error("No se encontró el bloque con la clase 'o_stock_barcode_main_menu'.");
//            return;
//        }
//
//        const h1Element = mainMenuElement.querySelector("h1");
//        if (!h1Element) {
//            console.error("No se encontró el elemento <h1> dentro del bloque.");
//            return;
//        }
//
//        if (mainMenuElement.querySelector(".employee-info")) {
//            console.log("El mensaje ya está presente, no se agrega de nuevo.");
//            return;
//        }
//
//        const welcomeDiv = document.createElement("div");
//        welcomeDiv.classList.add("employee-info", "text-center", "mb-4");
//
//        const h3Element = document.createElement("h3");
//        h3Element.textContent = `Bienvenido, ${employeeName}`;
//        welcomeDiv.appendChild(h3Element);
//
//        h1Element.parentNode.insertBefore(welcomeDiv, h1Element.nextSibling);
//    }
//    document.addEventListener(
//        "touchmove",
//        function (event) {
//            console.log("Movimiento táctil detectado:", event);
//        },
//        { passive: true }
//    );
//}
//
//export class MainMenuCustom extends Component {
//    static props = {
//        action: { type: Object, optional: true },
//        actionId: { type: Number, optional: true },
//        className: { type: String, optional: true },
//        globalState: { type: Object, optional: true },
//    };
//
//    setup() {
//        this.home = useService("home_menu");
//        this.actionService = useService("action");
//        this.orm = useService("orm");
//        this.state = useState({
//            manualInput: "",
//            employeeName: this._getStoredEmployeeName() || this.props.action?.additional_context?.employeeName || "",
//            welcomeMessage: this.props.action?.additional_context?.welcomeMessage || "",
//            errorMessage: "",
//            loading: false,
//        });
//    }
//
//    _getStoredEmployeeName() {
//        return localStorage.getItem('employeeName') || '';
//    }
//
//    _addDigit(digit) {
//      this.state.manualInput += digit;
//    }
//
//    async _submitBarcode() {
//        const barcode = this.state.manualInput;
//
//        // Validación: Campo vacío
//        if (!barcode) {
//            this.state.errorMessage = "Por favor, introduzca su número de usuario.";
//            console.log(this.state.errorMessage);
//            return;
//        }
//
//        this.state.loading = true;
//        this.state.errorMessage = "";
//        this.state.employeeName = "";
//
//        try {
//            const result = await this.orm.searchRead(
//                "hr.employee",
//                [["application_code_barcode", "=", barcode]],
//                ["name"],
//                { limit: 1 }
//            );
//
//            // Validación: Código no asociado
//            if (!result || result.length === 0) {
//                this.state.errorMessage = "No se encontró un empleado asociado a este código.";
//                console.log(this.state.errorMessage);
//                return;
//            }
//
//            let storedEmployeeName;
//
//            if (result.length > 0) {
//                storedEmployeeName = result[0].name;
//                localStorage.setItem('employeeName', storedEmployeeName);
//                this.state.employeeName = storedEmployeeName;
//
//                console.log("Nombre guardado en localStorage:", storedEmployeeName);
//                console.log("Verificación localStorage:", localStorage.getItem('employeeName'));
//            }
//
//            this.actionService.doAction('stock_barcode.stock_barcode_action_main_menu', {
//                additional_context: {
//                    employeeName: this.state.employeeName || 'Empleado',
//                },
//            }).then(() => {
//                setTimeout(() => {
//                    const currentStoredName = localStorage.getItem('employeeName');
//                    console.log("Valor actual en localStorage:", currentStoredName);
//                    const storedEmployeeName = localStorage.getItem('employeeName');
//                    const employeeName = this._getStoredEmployeeName();
//                    console.log(result[0].name);
//                    console.log(employeeName);
//                    const mainMenuElement = document.querySelector(".o_stock_barcode_main_menu");
//                    if (!mainMenuElement) {
//                        console.error("No se encontró el bloque con la clase 'o_stock_barcode_main_menu'.");
//                        return;
//                    }
//                }, 100);
//            });
//
//        } catch (error) {
//            console.error("Error al buscar el empleado:", error);
//            this.state.errorMessage = "Error al buscar el empleado. Intente nuevamente.";
//        } finally {
//            this.state.loading = false;
//            this._clearInput();
//        }
//    }
//
//    _clearInput() {
//        this.state.manualInput = "";
//        this.state.errorMessage = "";
//    }
//
//    goToMainMenu() {
//        this.home.toggle(true);
//    }
//}
//
//MainMenuCustom.template = "main_menu_custom";
//registry.category("actions").add("custom_barcode_main_menu", MainMenuCustom);

























