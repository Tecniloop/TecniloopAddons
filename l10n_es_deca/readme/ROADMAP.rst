Limitaciones conocidas
~~~~~~~~~~~~~~~~~~~~~~

* El módulo no puede determinar si un transporte está legalmente dentro del
  ámbito de aplicación o exento.
* No puede probar la política TLS, la disponibilidad externa, el tiempo
  confiable, la inmutabilidad de las copias de seguridad ni la veracidad de
  los datos introducidos por el operador.
* Deliberadamente no agrupa todo un lote en un único DeCA, porque un lote
  puede contener varios destinos y servicios de transporte.
* El DeCA administrativo no requiere firma. Por ello, el módulo base rechaza
  emitir la modalidad contractual sin un complemento de firma instalado.

Previsto
~~~~~~~~

* Ampliar ``l10n_es_deca_ades`` con adaptadores de firma remota para
  contraparte, prestador de confianza cualificado y HSM.
* Añadir adaptadores opcionales de entrega por SMS, WhatsApp o app móvil, sin
  convertirlos en condición de validez legal.
* Evaluar sugerencias automáticas de ámbito doméstico sin sustituir la
  decisión legal de aplicabilidad del operador.
* Añadir un módulo puente para proyectos OCA de e-CMR cuando su API objetivo
  para Odoo 19 esté acordada.
