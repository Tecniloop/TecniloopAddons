.. image:: https://odoo-community.org/readme-banner-image
   :target: https://odoo-community.org/get-involved?utm_source=readme
   :alt: Odoo Community Association

==============================================================================
España - Documento Electrónico de Control Administrativo del Transporte (DeCA)
==============================================================================
..
   !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
   !! Este fichero se ha actualizado manualmente para reflejar la    !!
   !! última descripción en español. No usar oca-gen-addon-readme    !!
   !! hasta trasladar estos textos de vuelta al repositorio OCA.     !!
   !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!

.. |badge1| image:: https://img.shields.io/badge/maturity-Beta-yellow.png
    :target: https://odoo-community.org/page/development-status
    :alt: Beta
.. |badge2| image:: https://img.shields.io/badge/license-AGPL--3-blue.png
    :target: http://www.gnu.org/licenses/agpl-3.0-standalone.html
    :alt: License: AGPL-3
.. |badge3| image:: https://img.shields.io/badge/github-OCA%2Fl10n--spain-lightgray.png?logo=github
    :target: https://github.com/OCA/l10n-spain/tree/19.0/l10n_es_deca
    :alt: OCA/l10n-spain
.. |badge4| image:: https://img.shields.io/badge/weblate-Translate%20me-F47D42.png
    :target: https://translation.odoo-community.org/projects/l10n-spain-19-0/l10n-spain-19-0-l10n_es_deca
    :alt: Translate me on Weblate
.. |badge5| image:: https://img.shields.io/badge/runboat-Try%20me-875A7B.png
    :target: https://runboat.odoo-community.org/builds?repo=OCA/l10n-spain&target_branch=19.0
    :alt: Try me on Runboat

|badge1| |badge2| |badge3| |badge4| |badge5|

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

**Tabla de contenidos**

.. contents::
   :local:

Instalación
===========

Instala el módulo en Odoo 19 Community junto con el módulo estándar
``stock_picking_batch``. Los paquetes Python ``qrcode`` y Pillow deben estar
disponibles en todos los workers de Odoo. Usa la versión de la librería PDF
fijada por los requisitos oficiales de Odoo 19.

Configuración
=============

* En Ajustes → Inventario → apartado **DeCA**, indica la URL pública HTTPS
  (``l10n_es_deca.public_base_url``) usada para el enlace de descarga y el QR.
* Si tienes instalado ``l10n_es_deca_intrastat``, en ese mismo apartado puedes
  elegir si la naturaleza de la mercancía se construye desde la descripción de
  la línea de venta/picking o desde el código CN8 de Intrastat.
* Exige TLS 1.2 o superior en el proxy inverso.
* Configura el hostname público y ``dbfilter`` para que no aparezca el
  selector de bases de datos.
* Usa los requisitos oficiales de Python de Odoo 19. El módulo admite el
  entorno fijado con ``PyPDF2`` en Python 3.10-3.12 y ``PyPDF`` en Python
  3.13+.
* Concede el grupo DeCA User o DeCA Manager a los usuarios de inventario
  autorizados.
* Define un procedimiento operativo de aplicabilidad, entrega al conductor,
  retención, tiempo confiable, copias de seguridad y monitorización del
  endpoint público.

Uso
===

#. Abre un albarán elegible y pulsa **Añadir a DeCA** en la cabecera (solo
   visible si el albarán aún no tiene uno). Como alternativa, pulsa **Crear
   documentos DeCA** en una agrupación de albaranes para crear un borrador por
   cada albarán.
#. También puedes seleccionar varios albaranes en la vista de lista y usar la
   acción **Añadir a DeCA** del menú ⚙️. Los albaranes que ya tuvieran un DeCA
   (o que estén completados/cancelados) se omiten y se informa de ello en un
   aviso.
#. Para abrir el DeCA ya creado de un albarán, usa el botón inteligente
   **DeCA** o el campo homónimo del formulario (junto al transportista, si
   tienes instalado ``l10n_es_deca_delivery``).
#. Revisa todos los valores precargados desde las existencias. Son
   sugerencias, no declaraciones legales.
#. Completa el transportista efectivo, el vehículo y el resto de datos
   obligatorios.
#. Emite y sella el PDF antes de que comience el transporte por carretera.
#. Registra la entrega del PDF o QR vigente al conductor.
#. Inicia el transporte del DeCA. Si los datos cambian, crea una revisión
   trazada y entrega la nueva versión.
#. Completa el DeCA cuando finalice el servicio.

Para un PDF que también se use con finalidad contractual, instala
``l10n_es_deca_ades`` antes de seleccionar **Administrativa y contractual**.
El módulo base rechaza deliberadamente emitir esa modalidad sin firmar.

Activa **DeCA obligatorio** en un albarán para impedir su validación hasta
que la versión sellada vigente tenga evidencia de entrega.

Desarrollo
==========

Do not edit ``README.rst`` or ``static/description/index.html`` directly. From the
``OCA/l10n-spain`` repository root, regenerate both files with::

    oca-gen-addon-readme --org-name=OCA --repo-name=l10n-spain \
        --branch=19.0 --addon-dir=l10n_es_deca

Incidencias conocidas / Hoja de ruta
=====================================

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

Rastreador de errores
======================

Los fallos se registran en `GitHub Issues
<https://github.com/OCA/l10n-spain/issues>`_. Si detectas un problema, por
favor revisa antes si ya se ha reportado. Si eres tú quien lo detecta,
ayúdanos a solucionarlo enviando información detallada y bien recibida
`aquí <https://github.com/OCA/l10n-spain/issues/new?body=module:%20l10n_es_deca%0Aversion:%2019.0%0A%0A**Steps%20to%20reproduce**%0A-%20...%0A%0A**Current%20behavior**%0A%0A**Expected%20behavior**>`_.

No contactes directamente con los colaboradores para pedir soporte o ayuda
sobre incidencias técnicas.

Créditos
========

Autores
-------

* Ecmr DeCA contributors

Colaboradores
-------------

* Ecmr DeCA project contributors

Mantenedores
------------

Este módulo es mantenido por Ecmr DeCA contributors.

.. image:: https://odoo-community.org/logo.png
   :alt: Odoo Community Association
   :target: https://odoo-community.org

Este módulo forma parte del proyecto `OCA/l10n-spain
<https://github.com/OCA/l10n-spain/tree/19.0/l10n_es_deca>`_.

Te invitamos a contribuir. Para saber cómo, visita
https://odoo-community.org/page/Contribute.
