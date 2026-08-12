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
