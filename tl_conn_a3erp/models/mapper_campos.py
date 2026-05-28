class TypeMapper:
    """Mapeo de Tipos de campos entre Odoo y a3ERP"""
    mapeo_campos = {
        'char': 'STRING',
        'text': 'STRING',
        'integer': 'INTEGER',
        'float': 'DECIMAL',
        'monetary': 'CURRENCY',
        'html': 'STRING',
        'date': 'STRING',
        'datetime': 'STRING',
        'boolean': 'BOOLEAN',
        'selection': 'STRING',
        'many2one': 'STRING',
    }
    
    def __init__(self):
        pass

    def traducir_campo(self, campo_odoo):
        return self.mapeo_campos.get(campo_odoo, 'ERROR')

class LangMapper:
    """Mapeo de Idiomas"""
    mapeo_campos = {
        'ca_ES': 'CAT',
        'es_ES': 'CAS',
        'en_US': 'ING',
        'en_GB': 'ING',
        'de_DE': 'ALE',
        'fr_FR': 'FRA',
        'gl_ES': 'GAL',
        'it_IT': 'ITA',
        'pt_PT': 'POR',
        'eu_ES': 'VAS',
    }
    
    def __init__(self):
        pass

    def traducir(self, valor, origen='odoo'):
        """
        Traduce un valor de idioma entre Odoo y a3ERP.
        Args:
            valor (str): El valor de idioma a traducir.
            origen (str): 'odoo' o 'a3erp', indica el origen del valor.
        Returns:
            str: El valor traducido.
        """
        if origen == 'odoo':
            return self.mapeo_campos.get(valor, valor)
        elif origen == 'a3erp':
            for clave, valor_a3erp in self.mapeo_campos.items():
                if valor_a3erp == valor:
                    return clave
        else:
            raise ValueError("Origen debe ser 'odoo' o 'a3erp'.")




