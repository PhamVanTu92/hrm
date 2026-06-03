# HRM Frontend

Next.js 14 (App Router) + TypeScript dashboard for the HRM system.

**Stack:** Next.js · TanStack Query + Table · React Hook Form + Zod · Zustand ·
shadcn/ui + Tailwind · axios (refresh-token interceptor). Mirrors the backend's
module layout under `src/features/`.

## Quick start (local dev)

```bash
cd frontend
cp .env.local.example .env.local        # point BACKEND_ORIGIN at the API
npm install
npm run dev                              # http://localhost:3000
```

The backend (FastAPI) must be running; `next.config.mjs` rewrites `/api/*` to
`BACKEND_ORIGIN` so the browser stays same-origin (no CORS, HttpOnly refresh
cookie works in dev).

## Docker (whole stack)

The frontend is built as a Next.js **standalone** image (see `Dockerfile`) and
is part of the backend's `docker-compose.yml`. From `backend/`:

```bash
docker compose up -d --build            # nginx + frontend + api + workers + db ...
# open http://localhost  (nginx routes / -> frontend, /api -> backend)
# show the Microsoft SSO button:
NEXT_PUBLIC_SSO_ENABLED=true docker compose up -d --build
```

`NEXT_PUBLIC_SSO_ENABLED` is a **build arg** (Next inlines `NEXT_PUBLIC_*` at
build time), so rebuild the image to toggle it.

## Layout

```
src/
├── app/                    # App Router
│   ├── (auth)/login/
│   └── (dashboard)/        # employees, attendance, approvals, payroll, payslips
├── components/
│   ├── ui/                 # shadcn primitives
│   ├── data-table/         # TanStack Table (server-side pagination/sort)
│   └── dynamic-form/       # metadata -> Zod -> RHF dynamic form
├── features/               # per-module api.ts + hooks.ts (mirror backend)
├── lib/                    # api-client (axios+refresh), query-client, rbac
├── stores/                 # zustand auth store
└── types/                  # types matching the backend envelope/schemas
```

## Auth model

- **Access token** in memory (Zustand) — attached as `Authorization: Bearer`.
- **Refresh token** in an HttpOnly Secure cookie — XSS-safe; the axios response
  interceptor auto-refreshes on `401` (deduped) and retries the request.
- After login, `/auth/me` populates `perms[]`; `<Can perm="...">` and the
  `middleware.ts` route guard hide UI — **the backend remains the real enforcer**.

## Scripts

```bash
npm run dev        # dev server
npm run build      # production build
npm run typecheck  # tsc --noEmit
npm run lint       # next lint
```
