# Partner Catastro para Odoo 18

Módulo para Odoo 18 que añade una pestaña **Catastro** a `res.partner` y un wizard para consultar los servicios web libres del Catastro a partir de una referencia catastral.

## Qué hace

- Añade una pestaña **Catastro** en la ficha del contacto.
- Añade un botón **Importar desde Catastro** que abre un wizard.
- Consulta el servicio **Consulta_DNPRC** para obtener datos catastrales no protegidos.
- Consulta opcionalmente **Consulta_CPMRC** para obtener coordenadas usando la finca (`refcat[:14]`).
- Guarda:
  - un resumen en campos del partner,
  - el payload JSON bruto,
  - todas las hojas/campos/valores devueltos por el webservice en una tabla auxiliar.

## Instalación

1. Copia la carpeta `partner_catastro` a tu ruta de addons.
2. Reinicia Odoo.
3. Actualiza la lista de aplicaciones.
4. Instala el módulo **Partner Catastro**.

## Configuración

Ve a **Ajustes > Ajustes generales** y busca la sección **Catastro**.

Puedes configurar:
- URL base servicio Callejero
- URL base servicio Coordenadas
- Timeout HTTP

## Uso

1. Abre un contacto.
2. Ve a la pestaña **Catastro**.
3. Pulsa **Importar desde Catastro**.
4. Indica la referencia catastral y, opcionalmente, provincia/municipio.
5. Confirma la importación.

## Notas funcionales

- `Consulta_DNPRC` admite referencias de 14, 18 o 20 posiciones.
- Si la referencia es de 14 posiciones, Catastro puede devolver una lista de inmuebles vinculados a la finca.
- `Consulta_CPMRC` trabaja con la finca de 14 posiciones.
- El módulo guarda el payload completo para no perder información aunque la respuesta cambie de estructura.


## Cambios en 18.0.1.0.1

- Corregida la extracción de los campos de resumen de Catastro para respuestas JSON con estructuras variables o listas.
- Corregida la detección de errores del servicio de coordenadas para no tratar `cuerr=0` como error.


## Corrección 18.0.1.0.2

- Soporte para la envoltura JSON real del Catastro (`consulta_dnprcResult` / `Consulta_CPMRCResult`).
- Extracción de resumen y dirección tanto para detalle completo (18/20 posiciones) como para listas por finca (14 posiciones).
