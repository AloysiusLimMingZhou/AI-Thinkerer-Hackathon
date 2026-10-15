"""Common paid-request boundary used by the server-side provider adapters."""
from contextlib import asynccontextmanager


class IntegrationUnavailable(RuntimeError):
    pass


@asynccontextmanager
async def paid_request(budget, context, quote):
    if budget is None:
        raise IntegrationUnavailable("A shared budget is required before calling an AI provider")
    reservation = budget.reserve(context, quote)
    budget.mark_dispatched(reservation.id)
    try:
        yield reservation
    except BaseException:
        # Includes cancellation: the provider may already have accepted the request.
        budget.mark_uncertain(reservation.id)
        raise
