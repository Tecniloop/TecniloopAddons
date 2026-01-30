from odoo import models, fields, api 

 
 

class HrLeaveType(models.Model): 
    _inherit = 'hr.leave.type' 

    virtual_remaining_display = fields.Char( 
        string='Saldo mostrado (hh:mm)', 
        compute='_compute_virtual_remaining_display', 
    ) 

    @api.depends('virtual_remaining_leaves') 
    def _compute_virtual_remaining_display(self): 
        for rec in self: 
            if rec.virtual_remaining_leaves: 
                total_hours = rec.virtual_remaining_leaves 
                hours = int(total_hours) 
                minutes = round((total_hours - hours) * 60) 
                rec.virtual_remaining_display = f"{hours}h {minutes:02d}m" 
            else: 
                rec.virtual_remaining_display = "0h 00m" 

    @api.model 
    def get_allocation_data_request(self, target_date=None, hidden_allocations=True): 
        # Llamamos al metodo original para obtener los datos base calculados por Odoo 
        res = super().get_allocation_data_request(target_date, hidden_allocations)
         
        # Iteramos sobre los resultados. 'res' es una lista de datos de los tipos de ausencia. 
        for name, data, requires_allocation, leave_type_id in res: 
            # Solo nos interesa modificar la visualización si la unidad es 'horas' 
            if data.get('request_unit') == 'hour': 
                # Obtenemos el valor decimal de hojas restantes (ej: 0.67) 
                total_hours = data.get('virtual_remaining_leaves', 0.0) 
                # Convertimos la parte entera a horas 
                hours = int(total_hours) 
                # Convertimos la parte decimal a minutos (0.67 * 60 = 40.2 -> 40) 
                minutes = round((total_hours - hours) * 60) 
                # Inyectamos el nuevo campo formateado 'virtual_remaining_display' en los datos 
                # Esto es lo que usará la vista XML del dashboard para mostrar "0h 40m" 
                data['virtual_remaining_display'] = f"{hours}h {minutes:02d}m" 
        
        return res 