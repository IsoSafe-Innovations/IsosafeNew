import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.deps import CurrentUser, rate_limited, require_viewer
from app.config import get_settings
from app.search.insights import generate_insights, get_cached_insights
from app.search.nl_search import SearchUnavailable, execute_search
from app.search.validator import SQLValidationError

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["search"])


class SearchRequest(BaseModel):
    query: str


@router.post("/search",
             dependencies=[Depends(rate_limited("search", limit=20, window_secs=60))])
async def nl_search(body: SearchRequest, user: CurrentUser = Depends(require_viewer)) -> dict:
    if not body.query.strip():
        raise HTTPException(status_code=422, detail="Empty query")
    try:
        return await execute_search(body.query.strip())
    except SearchUnavailable:
        raise HTTPException(status_code=503, detail="AI search is not configured on this node")
    except SQLValidationError as e:
        raise HTTPException(status_code=422, detail=f"Generated SQL rejected: {e}")
    except Exception:
        log.exception("search failed")
        raise HTTPException(status_code=500, detail="Search failed")


@router.get("/insights")
async def insights(user: CurrentUser = Depends(require_viewer)) -> dict:
    if not get_settings().anthropic_api_key:
        return {"available": False, "insights": [], "generated_at": None}
    cached = await get_cached_insights()
    if cached:
        return {"available": True, **cached}
    return {"available": True, "insights": [], "generated_at": None}


@router.post("/insights/refresh",
             dependencies=[Depends(rate_limited("insights", limit=4, window_secs=3600))])
async def refresh_insights(user: CurrentUser = Depends(require_viewer)) -> dict:
    if not get_settings().anthropic_api_key:
        raise HTTPException(status_code=503, detail="AI insights are not configured")
    insights_list = await generate_insights()
    cached = await get_cached_insights()
    return {"available": True, **(cached or {"insights": insights_list, "generated_at": None})}
