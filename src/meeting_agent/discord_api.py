from fastapi import APIRouter


def discord_router(transport):
    router=APIRouter()
    @router.get('/discord/status')
    async def status(): return transport.status()
    return router
