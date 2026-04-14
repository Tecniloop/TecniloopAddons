/** @odoo-module **/

import { Component, onMounted, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";

export class SignatureDialog extends Component {
    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");

        this.state = useState({
            certificates: [],
            selectedCertificate: null,
            enteredPin: "",
            isLoading: true,
        });

        onMounted(async () => {
            try {
                const certificates = await this.orm.call(
                    "res.users",
                    "get_my_assigned_certificates",
                    []
                );
                this.state.certificates = certificates || [];
                this.state.selectedCertificate = this.state.certificates[0] || null;
            } catch (error) {
                this.notification.add(_t("No se pudieron cargar los certificados asignados."), {
                    type: "danger",
                });
            } finally {
                this.state.isLoading = false;
            }
        });
    }

    selectCertificate(certificate) {
        this.state.selectedCertificate = certificate;
        this.state.enteredPin = "";
    }

    confirm() {
        const certificate = this.state.selectedCertificate;
        if (!certificate) {
            return;
        }

        if (!this.state.enteredPin) {
            this.notification.add(_t("Introduce el PIN de seguridad."), { type: 'warning' });
            return;
        }

        this.props.close();
        this.props.onResult({
            confirmed: true,
            certificate_id: certificate.id,
            pin: this.state.enteredPin,
        });
    }

    printWithoutSigning() {
        this.props.close();
        this.props.onResult({ confirmed: false, skipFirma: true });
    }

    cancel() {
        this.props.close();
        this.props.onResult({ confirmed: false });
    }
}
SignatureDialog.template = "l10n_firma_electronica.SignatureDialog";
SignatureDialog.components = { Dialog };