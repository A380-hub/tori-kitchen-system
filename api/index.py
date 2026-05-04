"""
TORI Kitchen Information System (KIS) — Backend API
Vercel Serverless (FastAPI) — Lightweight version
Uses Supabase REST API directly via httpx (no heavy SDK)
"""

import os
from datetime import datetime, timezone
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import httpx

app = FastAPI(title="TORI KIS")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")
REST_URL = f"{SUPABASE_URL}/rest/v1"

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=representation",
}


def now_iso():
    return datetime.now(timezone.utc).isoformat()


async def sb_get(table, params=""):
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{REST_URL}/{table}?{params}", headers=HEADERS)
        r.raise_for_status()
        return r.json()


async def sb_post(table, data):
    async with httpx.AsyncClient() as client:
        r = await client.post(f"{REST_URL}/{table}", headers=HEADERS, json=data)
        r.raise_for_status()
        return r.json()


async def sb_patch(table, params, data):
    async with httpx.AsyncClient() as client:
        r = await client.patch(f"{REST_URL}/{table}?{params}", headers=HEADERS, json=data)
        r.raise_for_status()
        return r.json()


@app.get("/")
async def root():
    return {"service": "TORI KIS", "status": "online"}


@app.post("/api/orders/submit")
async def submit_order(request: Request):
    body = await request.json()
    restaurant = body.get("restaurant")
    if restaurant not in ("r1", "r2"):
        raise HTTPException(400, "restaurant must be r1 or r2")
    await sb_patch("orders", f"restaurant=eq.{restaurant}&status=eq.active", {"status": "superseded"})
    row = {
        "restaurant": restaurant,
        "staff_name": body.get("staff_name", ""),
        "order_date": body.get("order_date", ""),
        "items": body.get("items", {}),
        "status": "active",
    }
    result = await sb_post("orders", row)
    return {"ok": True, "id": result[0]["id"] if result else None}


@app.post("/api/orders/amend")
async def amend_order(request: Request):
    body = await request.json()
    restaurant = body.get("restaurant")
    if restaurant not in ("r1", "r2"):
        raise HTTPException(400, "restaurant must be r1 or r2")
    await sb_patch("orders", f"restaurant=eq.{restaurant}&status=eq.active", {"status": "superseded"})
    row = {
        "restaurant": restaurant,
        "staff_name": body.get("staff_name", ""),
        "order_date": body.get("order_date", ""),
        "items": body.get("items", {}),
        "status": "active",
    }
    result = await sb_post("orders", row)
    return {"ok": True, "id": result[0]["id"] if result else None}


@app.get("/api/orders/active")
async def get_active_orders():
    active = await sb_get("orders", "status=eq.active&select=*")
    pending = {"r1": None, "r2": None}
    for row in active:
        rk = row["restaurant"]
        pending[rk] = {
            "id": row["id"],
            "restaurant": rk,
            "staffName": row.get("staff_name", ""),
            "orderDate": row.get("order_date", ""),
            "items": row.get("items", {}),
            "ts": to_ms(row.get("created_at")),
            "status": row["status"],
        }
    history_rows = await sb_get("orders", "status=in.(dispatched,delivered,accepted)&order=created_at.desc&limit=50&select=*")
    history = []
    for row in history_rows:
        history.append({
            "id": row["id"],
            "restaurant": row["restaurant"],
            "staff_name": row.get("staff_name", ""),
            "order_date": row.get("order_date", ""),
            "items": row.get("items", {}),
            "status": row["status"],
            "created_at": row.get("created_at"),
            "dispatched_at": row.get("dispatched_at"),
            "dispatched_by": row.get("dispatched_by"),
            "delivered_at": row.get("delivered_at"),
            "delivered_by": row.get("delivered_by"),
            "missing_items": row.get("missing_items", {}),
            "not_dispatched": row.get("not_dispatched", {}),
        })

    # Latest non-cleared prep submission — kitchen reads this as data.prep
    prep = None
    try:
        prep_rows = await sb_get("prep_logs", "cleared_at=is.null&order=created_at.desc&limit=1&select=*")
        if prep_rows:
            row = prep_rows[0]
            prep = {
                "id":          row.get("id"),
                "ts":          to_ms(row.get("created_at")),
                "staffName":   row.get("staff_name", ""),
                "prepDate":    row.get("prep_date", ""),
                "items":       row.get("items", {}),
                "items_order": row.get("items_order") or list((row.get("items") or {}).keys()),
            }
    except Exception:
        prep = None

    return {"r1": pending["r1"], "r2": pending["r2"], "history": history, "prep": prep}


@app.post("/api/orders/dispatch")
async def dispatch_orders(request: Request):
    body = await request.json()
    target = body.get("restaurant", "all")
    dispatched_by = body.get("dispatched_by", "")
    targets = ["r1", "r2"] if target == "all" else [target]
    updated = 0
    for rk in targets:
        update_data = {"status": "dispatched", "dispatched_at": now_iso(), "dispatched_by": dispatched_by}
        if body.get("missing_items"):
            update_data["missing_items"] = body["missing_items"]
        if body.get("not_dispatched"):
            update_data["not_dispatched"] = body["not_dispatched"]
        result = await sb_patch("orders", f"restaurant=eq.{rk}&status=eq.active", update_data)
        updated += len(result) if isinstance(result, list) else 0
    return {"ok": True, "dispatched": updated}


@app.post("/api/orders/delivered")
async def confirm_delivery(request: Request):
    body = await request.json()
    restaurant = body.get("restaurant")
    if restaurant not in ("r1", "r2"):
        raise HTTPException(400, "restaurant must be r1 or r2")
    result = await sb_patch("orders", f"restaurant=eq.{restaurant}&status=eq.dispatched", {
        "status": "delivered",
        "delivered_at": body.get("delivered_at", now_iso()),
        "delivered_by": body.get("delivered_by", ""),
    })
    return {"ok": True, "updated": len(result) if isinstance(result, list) else 0}


@app.post("/api/orders/accepted")
async def accept_delivery(request: Request):
    """Restaurant confirms they received the delivery — marks order as accepted."""
    body = await request.json()
    restaurant = body.get("restaurant")
    accepted_by = body.get("accepted_by", "")
    if restaurant not in ("r1", "r2"):
        raise HTTPException(400, "restaurant must be r1 or r2")
    result = await sb_patch("orders", f"restaurant=eq.{restaurant}&status=eq.delivered", {
        "status": "accepted",
    })
    return {"ok": True, "updated": len(result) if isinstance(result, list) else 0}


@app.post("/api/prep/submit")
async def submit_prep(request: Request):
    """Head chef submits prep log. If an active (non-cleared) prep exists, merge into it.
    Otherwise create a new one. Active prep is exposed as data.prep on /api/orders/active."""
    body = await request.json()
    items = body.get("items", {})
    # Normalise items to {task_id: qty} dict in case caller sent the verbose array shape
    if isinstance(items, list):
        items = {it.get("task_id"): it.get("qty") for it in items if it.get("task_id")}

    staff_name = body.get("staffName") or body.get("chef_name", "")
    prep_date  = body.get("prepDate")  or body.get("prep_date", "")

    # Look for existing active prep
    existing = await sb_get("prep_logs", "cleared_at=is.null&order=created_at.desc&limit=1&select=*")

    if existing:
        # Merge — overwrite qty for any duplicate task IDs, append new ones
        row = existing[0]
        merged_items = dict(row.get("items") or {})
        merged_items.update(items)  # new submission overwrites duplicates

        # Track newest-first ordering of items (for "new items at top of unticked list")
        merged_order = list((row.get("items_order") or [])) if row.get("items_order") else list(merged_items.keys())
        # Move newly-submitted IDs to the front (newest first)
        new_ids = list(items.keys())
        for nid in reversed(new_ids):
            if nid in merged_order:
                merged_order.remove(nid)
            merged_order.insert(0, nid)
        # Make sure every item in merged_items is somewhere in merged_order
        for k in merged_items.keys():
            if k not in merged_order:
                merged_order.append(k)

        update = {
            "items":        merged_items,
            "items_order":  merged_order,
            "staff_name":   staff_name or row.get("staff_name", ""),
            "prep_date":    prep_date  or row.get("prep_date", ""),
            "last_merge_at": now_iso(),
        }
        result = await sb_patch("prep_logs", f"id=eq.{row['id']}", update)
        return {"ok": True, "id": row["id"], "merged": True}
    else:
        new_row = {
            "staff_name":   staff_name,
            "prep_date":    prep_date,
            "day_index":    body.get("day_index"),
            "day_label":    body.get("day_label", ""),
            "items":        items,
            "items_order":  list(items.keys()),
            "items_detail": body.get("items_detail", []),
        }
        result = await sb_post("prep_logs", new_row)
        return {"ok": True, "id": result[0]["id"] if result else None, "merged": False}


@app.post("/api/prep/clear")
async def clear_prep(request: Request):
    """Mark latest active prep as cleared — kitchen has finished preparing the items."""
    body = await request.json() if await request.body() else {}
    prep_id = body.get("id")
    if prep_id:
        result = await sb_patch("prep_logs", f"id=eq.{prep_id}", {"cleared_at": now_iso()})
    else:
        # Clear the latest non-cleared prep
        latest = await sb_get("prep_logs", "cleared_at=is.null&order=created_at.desc&limit=1&select=id")
        if latest:
            result = await sb_patch("prep_logs", f"id=eq.{latest[0]['id']}", {"cleared_at": now_iso()})
        else:
            result = []
    return {"ok": True, "cleared": len(result) if isinstance(result, list) else 0}


@app.post("/api/prep/tick")
async def tick_prep_item(request: Request):
    """Kitchen ticks an individual item as prepared — records ticked_at timestamp.
    Body: {id: prep_log_id, item_id: 'task_id', ticked: true|false}
    When ticked=false, removes the timestamp."""
    body = await request.json()
    prep_id = body.get("id")
    item_id = body.get("item_id")
    ticked  = body.get("ticked", True)
    if not prep_id or not item_id:
        raise HTTPException(400, "id and item_id required")

    # Read current cleared_items
    rows = await sb_get("prep_logs", f"id=eq.{prep_id}&select=cleared_items")
    if not rows:
        raise HTTPException(404, "prep log not found")
    cleared_items = dict(rows[0].get("cleared_items") or {})

    if ticked:
        cleared_items[item_id] = now_iso()
    else:
        cleared_items.pop(item_id, None)

    await sb_patch("prep_logs", f"id=eq.{prep_id}", {"cleared_items": cleared_items})
    return {"ok": True, "cleared_items": cleared_items}


@app.get("/api/prep/history")
async def get_prep_history():
    """Cleared prep submissions only — pending ones live on /api/orders/active as data.prep."""
    rows = await sb_get("prep_logs", "cleared_at=not.is.null&order=cleared_at.desc&limit=200&select=*")
    history = []
    for row in rows:
        history.append({
            "id":            row.get("id"),
            "ts":            to_ms(row.get("created_at")),
            "staff_name":    row.get("staff_name", ""),
            "prep_date":     row.get("prep_date", ""),
            "day_index":     row.get("day_index"),
            "day_label":     row.get("day_label", ""),
            "items":         row.get("items", {}),
            "items_order":   row.get("items_order") or list((row.get("items") or {}).keys()),
            "items_detail":  row.get("items_detail", []),
            "cleared_items": row.get("cleared_items", {}),
            "created_at":    row.get("created_at"),
            "cleared_at":    row.get("cleared_at"),
        })
    return {"history": history}


@app.post("/api/admin/reset")
async def admin_reset(request: Request):
    """Clear all orders from the database. For testing/admin use only."""
    async with httpx.AsyncClient() as client:
        # Delete all orders
        r = await client.delete(
            f"{REST_URL}/orders?id=gt.0",
            headers=HEADERS
        )
    return {"ok": True, "message": "All orders cleared"}


def to_ms(iso_str):
    if not iso_str:
        return 0
    try:
        dt = datetime.fromisoformat(str(iso_str).replace("Z", "+00:00"))
        return int(dt.timestamp() * 1000)
    except Exception:
        return 0
