# CIE Control Dashboard

Operator console for the Company Intelligence Engine API. Vite + React 18 + TypeScript,
`react-router-dom` only — no UI framework, one stylesheet.

## Run locally

```bash
cd dashboard
npm install
VITE_API_BASE=http://localhost:8000/api npm run dev     # http://localhost:5173
```

`VITE_API_BASE` is the API root **including the `/api` prefix**. It is read at build/dev time and
used as the default; it can be overridden per browser on the **Settings** page, together with the
API key (`X-API-Key`). Both are kept in `localStorage`. Get a key from the backend:

```bash
cie migrate
cie bootstrap --tenant acme --company "Acme" --admin admin   # prints an admin API key
```

Other scripts: `npm run build` (type-checks with `tsc --noEmit`, then bundles to `dist/`),
`npm run typecheck`, `npm run preview`.

## Docker

```bash
docker build -t cie-dashboard --build-arg VITE_API_BASE=http://localhost:8000/api ./dashboard
docker run -p 5173:80 cie-dashboard
```

The image is multi-stage (node build → nginx). nginx serves `dist/` with
`try_files $uri /index.html` so deep links such as `/evidence/<doc>/<page>` work. Because the
API base is baked in at build time, pass `--build-arg VITE_API_BASE=...` (the root
`docker-compose.yml` sets it as an environment variable; move it to `build.args` if you need a
different value than the default).

## Panels

| Route | Panel | Endpoints |
| --- | --- | --- |
| `/search` | Company memory search + Ask | `POST /search`, `POST /answer` |
| `/scopes` | Department & project selector (drives `scope_id` everywhere; persisted) | `GET /scopes`, `GET /permissions/me` |
| `/documents` | Document library, versions, extraction, flags, upload | `GET /documents`, `/documents/{id}`, `/versions`, `/extraction`, `/flags`, `POST /ingest`, `POST /jobs/run`, `GET /jobs` |
| `/projects`, `/projects/:id` | Project map: objective, task DAG, ledger summary, messages, run | `GET/POST /projects`, `GET /projects/{id}`, `POST /projects/{id}/run`, `GET /messages` |
| `/agents` | Active agents with busy indicator | `GET /agents` |
| `/tasks` | Task queue; expand for assignment reason + candidate table | `GET /tasks` |
| `/graph` | Standalone dependency graph (same SVG DAG component) | `GET /projects/{id}` |
| `/ledger` | Decision ledger with chain validity, kind filter, hypothesis→test→result chains | `GET /projects/{id}/ledger` |
| `/conflicts` | Contradictions and open questions with history and links | `GET /memory/records`, `/history`, `/links` |
| `/evidence/:documentId/:pageNo?bbox=x0,y0,x1,y1&block=id` | Evidence viewer: page image with the cited bbox highlighted, block list, download | `GET /sources/{id}/pages/{n}`, `/image`, `/download` |
| `/performance` | Agent scorecards, routing score, low-support badge | `GET /agents/{id}/scorecards` |
| `/metrics` | Stat tiles + bar list | `GET /metrics/summary` |
| `/approvals` | Human approval queue | `GET /approvals`, `POST /approvals/{id}/decide` |
| `/settings` | API base URL and key | `GET /permissions/me` |

Every citation in the app (search results, answers, findings, records, glyphs) links to the
evidence viewer. Bboxes are in PDF points; the viewer scales them by the rendered image size
relative to the page's `width`/`height`. Page images and downloads are fetched with
`?api_key=` because `<img>`/`<a>` cannot send headers.

## Layout

```
src/
  api/        client.ts (fetch + error bus), endpoints.ts (typed calls), types.ts
  state/      settings, scope selection, toasts (React contexts)
  hooks/      useAsync, useLocalStorage
  components/ Layout, DagSvg, ScopeTree, CitationLink, GlyphCard, TaskDetail, RecordCard, ...
  pages/      one file per panel
  styles.css  design tokens (light/dark) and all component styles
```
