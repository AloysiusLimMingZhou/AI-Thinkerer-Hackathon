from fastapi import APIRouter,HTTPException

def discord_router(transport,attendance=None):
    router=APIRouter()
    @router.get('/discord/status')
    async def status():
        result=transport.status()
        if attendance:
            voice=attendance.status()
            result.update(voice)
            # Preserve notification readiness separately from voice provider readiness.
            result['notifications_configured']=transport.configured
        return result
    if attendance:
        @router.get('/sessions/{sid}/discord-attendance')
        async def attendance_status(sid:str):return attendance.status(sid)
        @router.post('/sessions/{sid}/discord-attendance/{action}')
        async def control(sid:str,action:str):
            attendance.status(sid)
            return await attendance.control(sid,action)
    return router
