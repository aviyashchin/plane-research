# Community agent teammates prototype

This research branch adds an opt-in Page sidebar for independently identified agents.
Set `VITE_AGENT_TEAMMATES=1` at build time. The default Community build keeps the feature disabled.
The sidebar reuses the current Plane theme and Page editor.

The sidebar requires a separately operated, authenticated backend:

| Page-relative endpoint    | Purpose                                                |
| ------------------------- | ------------------------------------------------------ |
| `agents/`                 | Authorized agents, runs, events, and human permissions |
| `agents/mentions/`        | Idempotent mention with agent ID, text, and nonce      |
| `agents/events/`          | SSE activity, replay cursor, and access revocation     |
| `agents/runs/:id/review/` | Approve or reject a research draft                     |
| `agents/runs/:id/cancel/` | Cancel execution                                       |

All endpoints are relative to `/api/workspaces/:slug/projects/:project/pages/:page/`.
POSTs use the native session and `/auth/get-csrf-token/`.
`/api/agents/source/` offers the running prototype's corresponding source to authorized network users.
The backend must recheck human and bot Page access at each action and runtime boundary.
The interface renders activity as plain text. Approval records a draft and must not accept market facts.

This branch does not provide Plane's commercial agent server or change the public Agent SDK contract.
The separately maintained integration supplies run storage, authority checks, and existing runtime adapters.
The opt-in sidebar is a prototype, not a complete native editor mention extension.

Build with the pinned package manager and lockfile:

```sh
pnpm install --frozen-lockfile
VITE_AGENT_TEAMMATES=1 VITE_LIVE_BASE_PATH=/live pnpm exec turbo build --filter=web --concurrency=2
```

Plane and these modifications remain under AGPL-3.0-only. Retain `LICENSE.txt` and provide the required source access.
