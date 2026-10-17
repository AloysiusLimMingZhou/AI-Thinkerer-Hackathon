from fastapi import APIRouter


def budget_router(budget):
    router = APIRouter()
    @router.get("/budget/status")
    async def status():
        return budget.status()
    return router
