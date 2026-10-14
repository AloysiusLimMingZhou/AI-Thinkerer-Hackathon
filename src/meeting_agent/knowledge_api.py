from fastapi import APIRouter, File, Form, HTTPException, UploadFile


def knowledge_router(knowledge):
    router=APIRouter()

    def require(session_id):
        if not knowledge.repository.get_session(session_id):
            raise HTTPException(404,'Session not found')

    @router.get('/sessions/{session_id}/knowledge', tags=['knowledge'])
    async def sources(session_id: str):
        require(session_id)
        return knowledge.list_sources(session_id)

    @router.post('/sessions/{session_id}/knowledge',status_code=201,tags=['knowledge'])
    async def upload(session_id: str,text: str=Form(''),files: list[UploadFile]=File(default=[])):
        require(session_id)
        return await knowledge.ingest(session_id,text,files)

    return router
