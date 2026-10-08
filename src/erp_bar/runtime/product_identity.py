"""Mission-local product pin, propagated through graph task contexts."""
from contextlib import contextmanager
from contextvars import ContextVar

_product_identity = ContextVar('erp_bar_product_identity', default=None)


def current_product_identity():
    return _product_identity.get()


@contextmanager
def bound_product_identity(product_id, query):
    value = None if product_id is None else {'product_id': product_id, 'query': query.strip().casefold()}
    token = _product_identity.set(value)
    try:
        yield
    finally:
        _product_identity.reset(token)
