from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status

from database import get_db
from deps import get_graphiti, verify_api_key
from engine.context_assembly import ContextBlockConfig, assemble_context_block
from engine.graphiti_engine import add_messages_to_graph, clear_session_graph
from models.memory import AddMemoryRequest, AddMemoryResponse, Fact, MemoryResponse

router = APIRouter(prefix="/api/v2/sessions", tags=["memory"])


@router.post(
    "/{session_id}/memory",
    response_model=AddMemoryResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(verify_api_key)],
)
async def add_memory(
    session_id: str,
    body: AddMemoryRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    db=Depends(get_db),
):
    # Verify session exists
    row = await (await db.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,))).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Session not found")

    graphiti = get_graphiti(request)
    messages = [m.model_dump() for m in body.messages]
    background_tasks.add_task(add_messages_to_graph, graphiti, session_id, messages)
    return AddMemoryResponse(ok=True)


@router.get(
    "/{session_id}/memory",
    response_model=MemoryResponse,
    dependencies=[Depends(verify_api_key)],
)
async def get_memory(
    session_id: str,
    request: Request,
    lastn: int = 10,
    max_tokens: int = 4000,
    include_summary: bool = True,
    min_rating: float = 0.0,
    query: str = "",
    db=Depends(get_db),
):
    row = await (await db.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,))).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Session not found")

    graphiti = get_graphiti(request)
    user_id = row["user_id"] if "user_id" in row.keys() and row["user_id"] else session_id
    context_block = await assemble_context_block(
        graphiti=graphiti,
        user_id=user_id,
        group_ids=[session_id],
        query=query,
        config=ContextBlockConfig(
            max_tokens=max_tokens,
            max_facts=lastn,
            include_summary=include_summary,
            include_dates=True,
            filter_invalid=True,
            min_score=min_rating,
        ),
    )

    facts = [
        Fact(
            uuid=fact.uuid,
            fact=fact.fact,
            created_at=fact.created_at.isoformat() if fact.created_at else None,
            valid_at=fact.valid_at.isoformat() if fact.valid_at else None,
            invalid_at=fact.invalid_at.isoformat() if fact.invalid_at else None,
            expired_at=fact.expired_at.isoformat() if fact.expired_at else None,
            score=fact.score,
        )
        for fact in context_block.facts
    ]
    return MemoryResponse(
        context=context_block.context,
        user_summary=context_block.user_summary,
        facts=facts,
        messages=[],
    )


@router.delete(
    "/{session_id}/memory",
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(verify_api_key)],
)
async def delete_memory(
    session_id: str,
    request: Request,
    db=Depends(get_db),
):
    row = await (await db.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,))).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Session not found")

    graphiti = get_graphiti(request)
    await clear_session_graph(graphiti, session_id)
    return {"message": "Memory deleted"}
