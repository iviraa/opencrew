"""News endpoints: what the press says about us and our neighbors, linked to projects and overlaps."""
from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth import current_user
from app.companies import companies, name
from app.crewly.app_tools import mine_sql
from app.db import get_conn
from app.news import feed
from app.news.classify import IMPACTS
from app.news.fetch import SOURCES

router = APIRouter(prefix="/api/app/news")


def partners_of(conn, company):
    rows = conn.execute(mine_sql(company)).fetchall()
    return sorted({r["a_org"] if r["b_org"] == company else r["b_org"] for r in rows})


@router.get("")
def list_news(days: int = Query(90, ge=1, le=365), impact: str | None = None, org: str | None = None, user=Depends(current_user), conn=Depends(get_conn)):
    if impact and impact not in IMPACTS:
        raise HTTPException(400, f"impact must be one of {IMPACTS}")
    if org and org not in companies():
        raise HTTPException(404, "unknown utility")
    me = user["company"]
    partners = partners_of(conn, me)
    orgs = [org] if org else [me, *partners]
    seen, items = set(), []
    for o in orgs:
        for it in feed.for_org(conn, o, days, impact):
            if it["id"] not in seen:
                seen.add(it["id"])
                items.append({**it, "mine": me in it["org_ids"], "about": [name(x) for x in it["org_ids"]]})
    items.sort(key=lambda x: (not x["mine"], not x["direct"], not x["affects_work"], x["published"] or ""), reverse=False)
    items.sort(key=lambda x: (x["mine"], x["direct"], x["affects_work"], x["published"] or ""), reverse=True)
    return {"items": items, "partners": partners, "impacts": IMPACTS, "sources": SOURCES}


@router.get("/{item_id}")
def one(item_id: int, user=Depends(current_user), conn=Depends(get_conn)):
    it = feed.one(conn, item_id)
    if not it:
        raise HTTPException(404, "no such story")
    return {**it, "about": [name(x) for x in it["org_ids"]]}


@router.post("/refresh")
def refresh(days: int = Query(90, ge=1, le=365), user=Depends(current_user), conn=Depends(get_conn)):
    me = user["company"]
    return feed.run(conn, [me, *partners_of(conn, me)], days)
