from . import models
from . import wizards

def _enable_auto_fetch_post_init(env):
    env['ir.config_parameter'].sudo().set_param("eg_app_base.is_auto_fetch_apps", True)