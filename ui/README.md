# research-agent UI

**HTTP API перенесён в пакет:** `planner_agent.http_api` (импорт `create_app`,
`ApiSettings` оттуда же). Этот каталог по-прежнему может содержать статический
`analyst_ui` для локальной разработки.

This directory contains the future repository-like research UI and optional
static assets.

Primary screens:

- Runs List
- Run Graph
- Node Inspector
- Artifact Browser
- Branch Workspace
- Feedback Panel
- Review Queue

Chat is a secondary input surface. The primary object is `ResearchRun`.

## Static analyst UI

The first working interface is in `ui/analyst_ui/`.

It uses only browser-native files (no bundler), for example:

- `analyst_ui/index.html`, `styles.css`, `common.js`, `home.js`
- дополнительные страницы: `history.html`, `report.html`, `files.html`, `followup.html`, `audit.html`, `settings.html`

There are no npm packages, CDN links, build tools, React/Vue, or external UI
frameworks. When the FastAPI app is created through `planner_agent.http_api:create_app`, the
folder is mounted automatically at:

```text
http://127.0.0.1:8000/app/
```

The interface is intentionally analyst-first:

- the home screen is task input plus a post-run graph canvas;
- the final report, artifacts, follow-up, and audit live on separate pages;
- follow-up questions reuse the selected run via `?run=` in the URL.

## API

The current API is in `ui/api/`. It is intentionally thin: it exposes existing
agent storage/read services and does not create models or use API keys.

Implemented endpoints:

- `GET /api/v1/health`
- `GET /api/v1/runs`
- `POST /api/v1/runs/invoke`
- `GET /api/v1/runs/{run_id}`
- `GET /api/v1/runs/{run_id}/result`
- `GET /api/v1/runs/{run_id}/graph`
- `GET /api/v1/runs/{run_id}/nodes`
- `GET /api/v1/runs/{run_id}/nodes/{node_id}`
- `GET /api/v1/runs/{run_id}/nodes/{node_id}/inspector`
- `GET /api/v1/runs/{run_id}/artifacts`
- `GET /api/v1/runs/{run_id}/artifacts/{artifact_id}`
- `GET /api/v1/runs/{run_id}/artifacts/{artifact_id}/preview`
- `GET /api/v1/runs/{run_id}/artifacts/{artifact_id}/text`
- `POST /api/v1/branches`
- `POST /api/v1/branches/invoke`
- `POST /api/v1/dialog-context`

Example:

```python
from planner_agent.http_api import ApiSettings, create_app

app = create_app(
    settings=ApiSettings(
        workspace_root=".",
        runs_dir="examples/runs",
    )
)
```

Agent invoke endpoints require an already constructed `ResearchAgent`:

```python
from planner_agent.http_api import create_app
from planner_agent.http_api.config import ApiServices

services = ApiServices(
    lineage_service=agent.lineage_service,
    artifact_service=agent.artifact_service,
    inspection_service=agent.inspection_service,
    dialog_context_service=agent.dialog_context_service,
    agent=agent,
)

app = create_app(services=services)
```

The API layer does not import `model.py` and does not create model clients or
tools by itself.

Dialog context preview:

```json
{
  "user_query": "Compare base run with branch run",
  "context_runs": [
    {
      "run_id": "base-run-id",
      "role": "base",
      "include_final_report": true,
      "include_artifacts": true
    },
    {
      "run_id": "branch-run-id",
      "role": "branch",
      "include_final_report": true,
      "include_artifacts": true
    }
  ]
}
```

Run locally after installing the optional API dependencies:

```bash
uvicorn planner_agent.http_api:create_app --factory --reload
```
