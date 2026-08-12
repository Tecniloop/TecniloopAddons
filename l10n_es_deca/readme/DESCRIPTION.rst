Emite el Documento electrónico de Control Administrativo del transporte (DeCA)
español desde las transferencias de existencias de Odoo 19 Community. Cada
documento sella un PDF español canónico con un código QR que descarga
directamente ese mismo PDF, sin inicio de sesión ni pasos intermedios.

Un DeCA está vinculado a un único ``stock.picking``. Cuando los documentos se
crean desde una ``stock.picking.batch`` (agrupación de albaranes), el módulo
crea uno por albarán y conserva la referencia del lote como trazabilidad. Así
se evita presentar un lote con varios destinos como un único servicio de
transporte.

El módulo base es deliberadamente administrativo y no firma los PDF. Instala
``l10n_es_deca_ades`` únicamente cuando el mismo documento también se use con
finalidad contractual y las partes deban firmarlo con PAdES.

Módulos puente opcionales
~~~~~~~~~~~~~~~~~~~~~~~~~

* ``l10n_es_deca_delivery`` (requiere ``delivery_carrier_partner``): precarga
  el transportista efectivo del DeCA a partir del contacto asignado al
  transportista (``delivery.carrier``). Si además está instalado el módulo
  ``fleet``, busca un vehículo cuyo conductor esté relacionado con ese
  contacto y sugiere su matrícula como tractora.
* ``l10n_es_deca_intrastat`` (requiere ``intrastat_product``): añade en
  Ajustes de Inventario, dentro del apartado **DeCA**, la opción de construir
  la naturaleza de la mercancía a partir del código CN8 de Intrastat
  (agrupando por código y unidad de medida) en lugar de la descripción de la
  línea de venta o del producto del picking.
