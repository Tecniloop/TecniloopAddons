from odoo import fields,models,api, _

class ProductProduct(models.Model):
    _inherit = ['product.product']       
        
    def get_product_multiline_description_sale(self):
        """Computar la descripción de la linia."""
        name = self.name
        if self.description_sale and not self.default_code:
            name += '\n' + self.name + '\n' + self.description_sale            
        elif self.description_sale:
            name += '\n' + self.description_sale
        elif self and not self.default_code:
            name += '\n' + self.name
            
        return name