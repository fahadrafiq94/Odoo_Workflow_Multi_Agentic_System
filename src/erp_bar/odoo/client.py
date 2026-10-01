from functools import lru_cache

from erp_bar.odoo.bridge import OdooBridge


@lru_cache(maxsize=1)
def get_odoo_bridge() -> OdooBridge:
    """
    Return one authenticated Odoo XML-RPC bridge.

    The connection is created lazily on first use,
    rather than when Python imports the tool modules.
    """

    return OdooBridge()