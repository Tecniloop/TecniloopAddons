/** @odoo-module **/
import { registry } from "@web/core/registry";
import { SignatureDialog } from "@l10n_firma_electronica/js/signature_dialog";

const electronicSignatureHandler = async (action, options, env) => {
    if (action.report_type !== 'qweb-pdf') {
        return;
    }

    // If the user has no assigned certificates, keep Odoo's normal print flow.
    try {
        const certificates = await env.services.orm.call(
            "res.users",
            "get_my_assigned_certificates",
            []
        );
        if (!certificates || certificates.length === 0) {
            return;
        }
    } catch {
        return;
    }

    if (document.activeElement && typeof document.activeElement.blur === "function") {
        document.activeElement.blur();
    }

    const result = await new Promise((resolve) => {
        env.services.dialog.add(SignatureDialog, {
            onResult: resolve,
        });
    });

    if (!result || !result.confirmed) {
        if (result && result.skipFirma) {
            return;
        }
        if (options.onClose) {
            options.onClose();
        }
        return true; 
    }

    const context = {
        ...(action.context || {}),
        ...(options.context || {}),
        electronic_signature_confirmed: true,
        electronic_signature_certificate_id: result.certificate_id,
        electronic_signature_pin: result.pin,
    };

    action.context = context;
    options.context = context;
    return;
};

registry.category("ir.actions.report handlers").add(
    "l10n_firma_electronica_handler", electronicSignatureHandler, { sequence: 1 }
);