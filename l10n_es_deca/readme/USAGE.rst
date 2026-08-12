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
