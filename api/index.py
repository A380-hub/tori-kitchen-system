"""
TORI Kitchen Information System (KIS) — Backend API
Vercel Serverless (FastAPI)

Endpoints:
  POST /api/orders/submit     — Restaurant staff submits new order
  POST /api/orders/amend      — Restaurant staff amends existing order
  GET  /api/orders/active     — Kitchen board fetches active orders
  POST /api/orders/dispatch   — Kitchen dispatches order(s)
  POST /api/orders/delivered  — Driver confirms delivery
  POST /api/prep/submit       — Kitchen submits prep checklist
"""

import os
import json
from datetime import datetime, timezone
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from supabase import create_client, Client

app = FastAPI(title="TORI KIS")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Supabase client ──
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


def now_iso():
    return datetime.now(timezone.utc).isoformat()


# ═══════════════════════════════════════
# POST /api/orders/submit
# ═══════════════════════════════════════
@app.post("/api/orders/submit")
async def submit_order(request: Request):
    body = await request.json()
    restaurant = body.get("restaurant")  # "r1" or "r2"
    if restaurant not in ("r1", "r2"):
        raise HTTPException(400, "restaurant must be r1 or r2")

    # Supersede any existing active order for this restaurant
    supabase.table("orders") \
        .update({"status": "superseded"}) \
        .eq("restaurant", restaurant) \
        .eq("status", "active") \
        .execute()

    # Insert new order
    row = {
        "restaurant": restaurant,
        "staff_name": body.get("staff_name", ""),
        "order_date": body.get("order_date", ""),
        "items": body.get("items", {}),
        "status": "active",
    }
    result = supabase.table("orders").insert(row).execute()
    return {"ok": True, "id": result.data[0]["id"] if result.data else None}


# ═══════════════════════════════════════
# POST /api/orders/amend
# ═══════════════════════════════════════
@app.post("/api/orders/amend")
async def amend_order(request: Request):
    body = await request.json()
    restaurant = body.get("restaurant")
    if restaurant not in ("r1", "r2"):
        raise HTTPException(400, "restaurant must be r1 or r2")

    # Supersede old active order
    supabase.table("orders") \
        .update({"status": "superseded"}) \
        .eq("restaurant", restaurant) \
        .eq("status", "active") \
        .execute()

    # Insert amended order (same logic as submit, but flagged)
    row = {
        "restaurant": restaurant,
        "staff_name": body.get("staff_name", ""),
        "order_date": body.get("order_date", ""),
        "items": body.get("items", {}),
        "status": "active",
    }
    result = supabase.table("orders").insert(row).execute()
    return {"ok": True, "id": result.data[0]["id"] if result.data else None}


# ═══════════════════════════════════════
# GET /api/orders/active
# ═══════════════════════════════════════
@app.get("/api/orders/active")
async def get_active_orders():
    result = supabase.table("orders") \
        .select("*") \
        .eq("status", "active") \
        .execute()

    pending = {"r1": None, "r2": None}
    for row in (result.data or []):
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

    # Also fetch recent history (last 50 dispatched/delivered)
    hist_result = supabase.table("orders") \
        .select("*") \
        .in_("status", ["dispatched", "delivered"]) \
        .order("created_at", desc=True) \
        .limit(50) \
        .execute()

    history = []
    for row in (hist_result.data or []):
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

    return {"r1": pending["r1"], "r2": pending["r2"], "history": history}


# ═══════════════════════════════════════
# POST /api/orders/dispatch
# ═══════════════════════════════════════
@app.post("/api/orders/dispatch")
async def dispatch_orders(request: Request):
    body = await request.json()
    target = body.get("restaurant", "all")  # "r1", "r2", or "all"
    dispatched_by = body.get("dispatched_by", "")
    missing_items = body.get("missing_items", {})
    not_dispatched = body.get("not_dispatched", {})

    targets = ["r1", "r2"] if target == "all" else [target]
    updated = 0

    for rk in targets:
        update_data = {
            "status": "dispatched",
            "dispatched_at": now_iso(),
            "dispatched_by": dispatched_by,
        }
        if missing_items:
            update_data["missing_items"] = missing_items
        if not_dispatched:
            update_data["not_dispatched"] = not_dispatched

        result = supabase.table("orders") \
            .update(update_data) \
            .eq("restaurant", rk) \
            .eq("status", "active") \
            .execute()
        updated += len(result.data or [])

    return {"ok": True, "dispatched": updated}


# ═══════════════════════════════════════
# POST /api/orders/delivered
# ═══════════════════════════════════════
@app.post("/api/orders/delivered")
async def confirm_delivery(request: Request):
    body = await request.json()
    restaurant = body.get("restaurant")
    delivered_by = body.get("delivered_by", "")
    delivered_at = body.get("delivered_at", now_iso())

    if restaurant not in ("r1", "r2"):
        raise HTTPException(400, "restaurant must be r1 or r2")

    result = supabase.table("orders") \
        .update({
            "status": "delivered",
            "delivered_at": delivered_at,
            "delivered_by": delivered_by,
        }) \
        .eq("restaurant", restaurant) \
        .eq("status", "dispatched") \
        .execute()

    return {"ok": True, "updated": len(result.data or [])}


# ═══════════════════════════════════════
# POST /api/prep/submit
# ═══════════════════════════════════════
@app.post("/api/prep/submit")
async def submit_prep(request: Request):
    body = await request.json()
    # For now, log prep data. Can be expanded to a prep_logs table later.
    return {"ok": True, "received": True}


# ═══════════════════════════════════════
# GET / — health check
# ═══════════════════════════════════════
@app.get("/")
async def root():
    return {"service": "TORI KIS", "status": "online"}


# ── Helper ──
def to_ms(iso_str):
    if not iso_str:
        return 0
    try:
        dt = datetime.fromisoformat(str(iso_str).replace("Z", "+00:00"))
        return int(dt.timestamp() * 1000)
    except Exception:
        return 0
