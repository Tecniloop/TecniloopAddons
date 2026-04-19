# Notas funcionales

## project_tier_validation
- Se dispara la validación cuando un proyecto pasa de una etapa abierta a una etapa plegada (`fold=True`).
- Al reabrir el proyecto (volver a una etapa no plegada) se reinicia el circuito de reviews, igual que en otros addons de tier validation.

## project_task_tier_validation
- Se dispara la validación cuando una tarea pasa a `Done` (`1_done`) o `Cancelled` (`1_canceled`).
- Se ha añadido `date_last_stage_update` como excepción técnica para no romper la escritura interna de `project.task` después del cambio de estado.

## Validación realizada
- Compilación Python (`compileall`) OK.
- XML bien formado (`lxml.etree.parse`) OK.
- No se ha ejecutado un servidor Odoo 18 completo ni la suite real de tests en este entorno.
