from . import models
from . import controllers


def post_init_hook(env):
    env["es.index.config"].sudo().create_default_product_search_config()
