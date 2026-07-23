* Generación nativa del modelo 190 (requiere integración con
  ``l10n_es_aeat_mod190``).
* Aplicación de la distribución analítica (registros ``D``) sobre
  ``analytic_distribution`` de las líneas de asiento.
* 
* Reproceso selectivo por tipo de registro desde las líneas del lote.

* Idempotencia por identificador de factura y huella del asiento para impedir duplicados en reimportaciones.
