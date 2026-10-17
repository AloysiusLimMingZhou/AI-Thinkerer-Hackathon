from fastapi import APIRouter, Query, Response
from pydantic import BaseModel, ConfigDict, Field
from .models import SessionCreate


class BriefingPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1,max_length=200)
    owner_name: str = Field(min_length=1,max_length=100)
    agent_name: str = Field(min_length=1,max_length=100)


def briefing_router(service):
    router = APIRouter()
    @router.get("/briefings")
    async def list_briefings(query: str = Query("",max_length=200), include_drafts: bool = False):
        return service.list(query,include_drafts=include_drafts)
    @router.post("/briefings",status_code=201)
    async def create(payload: SessionCreate):
        return service.create(payload)
    @router.patch("/briefings/{id}")
    async def update(id: str,payload: BriefingPatch):
        return service.update(id,**payload.model_dump())
    @router.post("/briefings/{id}/prepare")
    async def prepare(id: str):
        return service.prepare(id)
    @router.delete("/briefings/{id}",status_code=204)
    async def delete(id: str):
        service.delete(id)
        return Response(status_code=204)
    return router
