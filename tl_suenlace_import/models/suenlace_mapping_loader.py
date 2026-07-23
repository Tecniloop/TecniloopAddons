# Copyright 2026 Tecniloop
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
import logging

from odoo import api, models


_logger = logging.getLogger(__name__)


class SuenlaceMappingLoader(models.AbstractModel):
    """Servicio idempotente para cargar la configuración inicial SUENLACE."""

    _name = "tl.suenlace.mapping.loader"
    _description = "Cargador de mapeos predeterminados SUENLACE"

    @api.model
    def _is_spanish_company(self, company):
        fiscal_country = company.account_fiscal_country_id or company.country_id
        return bool(
            fiscal_country
            and fiscal_country.code == "ES"
            and company.chart_template
        )

    @api.model
    def load_for_company(self, company):
        """Carga mapeos seguros para ``company`` sin alterar los existentes."""
        company.ensure_one()
        result = {
            "company": company,
            "tax_created": 0,
            "tax_skipped": [],
            "fiscal_created": 0,
            "fiscal_skipped": [],
        }
        if not self._is_spanish_company(company):
            return result

        context = {
            **self.env.context,
            "allowed_company_ids": [company.id],
            "company_id": company.id,
        }
        tax_model = (
            self.env["tl.suenlace.tax.mapping"]
            .with_company(company)
            .with_context(context)
            .sudo()
        )
        fiscal_model = (
            self.env["tl.suenlace.fiscal.position.mapping"]
            .with_company(company)
            .with_context(context)
            .sudo()
        )
        tax_stats = tax_model.load_default_mappings(company)
        fiscal_stats = fiscal_model.load_default_mappings(company)
        result.update(
            {
                "tax_created": tax_stats["created"],
                "tax_skipped": tax_stats["skipped"],
                "fiscal_created": fiscal_stats["created"],
                "fiscal_skipped": fiscal_stats["skipped"],
            }
        )
        return result

    @api.model
    def load_for_spanish_companies(self):
        """Punto de entrada XML: se ejecuta al instalar y al actualizar."""
        companies = self.env["res.company"].sudo().search([])
        results = []
        for company in companies:
            if not self._is_spanish_company(company):
                continue
            try:
                with self.env.cr.savepoint():
                    result = self.load_for_company(company)
                    results.append(result)
                    _logger.info(
                        "SUENLACE defaults for company %s: %s tax mappings and "
                        "%s fiscal-position mappings created",
                        company.display_name,
                        result["tax_created"],
                        result["fiscal_created"],
                    )
            except Exception:
                # Un plan contable personalizado no debe impedir la instalación
                # del importador. El asistente permite reintentar y revisar.
                _logger.exception(
                    "Could not load default SUENLACE mappings for company %s",
                    company.display_name,
                )
        return True
