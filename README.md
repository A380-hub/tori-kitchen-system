# TORI Kitchen Information System (KIS)

Ordering, preparation and dispatch system for TORI Street Food (two restaurants:
Tori 1 — Špansko `r1`, Tori 2 — Trnje `r2`).

## Live URLs

- **App (primary):** https://tori-kitchen-system.vercel.app/ — serves the frontend **and** the `/api` backend.
- **Mirror:** https://a380-hub.github.io/tori-kitchen-system/ (GitHub Pages, same code).
- **Operation Center hub:** https://tori-agentic-ai.vercel.app/ (separate repo `a380-hub/tori-agentic-ai`) → its "TORI Kitchen" tile links here.

## Architecture

- **Frontend** — 6 self-contained static HTML pages (inline CSS/JS, base64 logo). No build step.
- **Backend** — FastAPI in `api/index.py` (Vercel Python function), proxies Supabase via `httpx`.
- **Database** — Supabase project `skrecohmpufrhkdjrwas` (Postgres + REST).
- **Hosting** — one Vercel project `tori-kitchen-system` serves both (see `vercel.json`:
  `*.html` static + `/api/(.*)` → `api/index.py`). Also mirrored on GitHub Pages from `main` root.
- Every page calls the backend at `https://tori-kitchen-system.vercel.app` and reads the
  catalog directly from Supabase with the **anon** key (read-only).

## Pages / modules

| File | Role | Notes |
|---|---|---|
| `index.html` | Role-based hub | PIN login; shows module tiles per the user's role. Admins also see an **Admin** tile. |
| `tori-order-checklist.html` | Kitchen Order | Place/amend orders; category nav + **search** + **sort** (Frequent / A‑Z). |
| `tori-kitchen-system.html` | Kitchen Display | Live R1/R2 orders, prep column, **Delivery History** + **Preparation History** (newest first). |
| `tori-prep-checklist.html` | Prep List | Head-chef prep submissions. |
| `tori-dispatch-delivery.html` | Dispatch / Delivery | Packing + delivery flow. |
| `admin.html` | Admin Panel | Users, data-clear tools, **Order Units** + **Order Items** (dual quantity). Master code `2601`, or auto-entry when arriving as a logged-in admin. |

## Roles & access

Roles live on `users.groups` (e.g. `{admin,order,display,prep,delivery}`). The hub maps roles →
modules via `ROLE_ACCESS`. `admin` unlocks everything incl. the admin panel. The Admin tile is
shown only to admins; `admin.html` skips its master-code screen when the visitor is a verified
admin (re-checked against the DB), otherwise requires `2601`.

## Data model (Supabase)

- `order_items` — catalog (113 seed items). Columns incl. `id` (text PK, **immutable**, matches order
  payload keys), `name`, `category`, `output_unit`, `dual_enabled`, `order_unit_id`, `factor`,
  `sort_order`, **`archived`**. RLS: anon `SELECT` only; writes via the service-role key (admin).
- `order_units` — editable unit labels for dual quantity (single `name`, no plural).
- `orders` — submitted orders (`items` JSON `{item_id: qty}`, status flow active→dispatched→delivered→accepted).
- `prep_logs`, `prep_tasks`, `users` — prep history, custom prep tasks, staff/PINs.
- RPC `item_order_counts()` (SECURITY DEFINER, anon-callable) — returns `{item_id, cnt}` for the
  "Frequently ordered" sort.

### Dual quantity

Some items are ordered in a unit (e.g. *Container*) but every screen also shows the kitchen output.
Conversion is **display-time only** (order payload unchanged): `qty × factor`, rounded (pcs → whole;
kg/L → 2dp, trailing zeros dropped). Format: `3 Container (15 kg)`. Configure per item in admin.
Shared helpers (`formatQtyDisplay`/`unitLabel`/`dualWord`/`dualPreview`/`roundOut`) are identical
across the 3 display pages; single-unit items render exactly as before.

### Delete = archive (soft delete)

Deleting an item sets `archived=true` — the row is **never** removed, so historical orders always
resolve the item's name. Archived items are hidden from the order checklist but kept in lookups;
they can be restored. Admin "+ Add item" generates a fresh unique id that never reuses an
existing/archived id, and offers Restore if the name matches an archived item.

## Order checklist: search & sort

Search filters across all non-archived items. Sort toggle: **Frequent** (default — ranks by how
often each item was ordered, from `item_order_counts()`) and **A‑Z**. Category dropdown retained;
entered quantities persist across views.

## Develop & deploy

Source of truth is **GitHub** (`a380-hub/tori-kitchen-system`). Edit → commit → `git push origin main`
→ Vercel auto-deploys (and GitHub Pages rebuilds). No local build. Verify on the `*.vercel.app` URL.
The HTML files are UTF‑8 (no BOM) with multibyte chars — edit with tools that preserve UTF‑8 (do not
re-save via PowerShell `Set-Content -Encoding utf8`, which adds a BOM / mojibake on Windows‑1252).

Rollback point for the pre-dual-quantity production: git tag `prod-backup-2026-06-27`.
