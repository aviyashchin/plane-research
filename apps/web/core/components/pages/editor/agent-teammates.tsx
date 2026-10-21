/**
 * Copyright (c) 2026-present Plane research fork contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 */
import { useCallback, useEffect, useRef, useState } from "react";

type Teammate = { id: string; user_id: string; name: string; avatar: string; runtime: string };
type Run = { id: string; agent_id: string; human_id: string; status: string; reviewer_id: string | null };
type Activity = { id: number; run_id: string; actor_id: string; type: string; text: string; at: string };
type State = { agents: Teammate[]; runs: Run[]; events: Activity[]; can_act: boolean; current_user_id: string };

export function AgentTeammates({
  workspaceSlug,
  projectId,
  pageId,
}: {
  workspaceSlug: string;
  projectId: string;
  pageId: string;
}) {
  const base = `/api/workspaces/${encodeURIComponent(workspaceSlug)}/projects/${projectId}/pages/${pageId}/agents/`;
  const [state, setState] = useState<State | null>(null);
  const [selected, setSelected] = useState("");
  const [text, setText] = useState("");
  const [error, setError] = useState("");
  const [connection, setConnection] = useState("Connecting");
  const [busy, setBusy] = useState(false);
  const stream = useRef<EventSource | null>(null);
  const nonce = useRef(crypto.randomUUID());
  const refresh = useCallback(async () => {
    const response = await fetch(base, { credentials: "same-origin", cache: "no-store" });
    if (!response.ok) throw new Error(`Workspace access unavailable (${response.status})`);
    const next: State = await response.json();
    // Concurrent stream refreshes can return out of order. Keep the newer audit cursor.
    setState((previous) =>
      previous && (previous.events.at(-1)?.id ?? 0) > (next.events.at(-1)?.id ?? 0) ? previous : next
    );
    setSelected((id) => id || next.agents[0]?.id || "");
    return next;
  }, [base]);

  useEffect(() => {
    let disposed = false;
    void refresh()
      .then((initial) => {
        if (disposed) return null;
        const cursor = initial.events.at(-1)?.id ?? 0;
        const source = new EventSource(`${base}events/?after=${cursor}`);
        stream.current = source;
        source.addEventListener("open", () => setConnection("Live"));
        source.addEventListener("error", () => setConnection("Reconnecting"));
        source.addEventListener("activity", (message) => {
          const activity: Activity = JSON.parse((message as MessageEvent<string>).data);
          setState((previous) =>
            previous
              ? {
                  ...previous,
                  // oxlint-disable-next-line unicorn/no-array-sort -- The project targets ES2022; this array is a fresh copy.
                  events: [...previous.events.filter((e) => e.id !== activity.id), activity].sort(
                    (a, b) => a.id - b.id
                  ),
                }
              : previous
          );
          if (
            ["proposal", "approved", "rejected", "cancelled", "error", "progress", "mention"].includes(activity.type)
          ) {
            void refresh().catch(() => {
              source.close();
              setState(null);
              setError("Workspace access revoked or unavailable");
            });
          }
        });
        source.addEventListener("revoked", () => {
          source.close();
          setState(null);
          setConnection("Access revoked");
          setError("Workspace access revoked or unavailable");
        });
        return source;
      })
      .catch((cause: Error) => {
        if (!disposed) setError(cause.message);
      });
    return () => {
      disposed = true;
      stream.current?.close();
    };
  }, [base, refresh]);

  async function act(path: string, payload: object) {
    setBusy(true);
    setError("");
    try {
      const csrfResponse = await fetch("/auth/get-csrf-token/", { credentials: "same-origin", cache: "no-store" });
      if (!csrfResponse.ok) throw new Error("Request verification unavailable");
      const csrf: { csrf_token: string } = await csrfResponse.json();
      const response = await fetch(base + path, {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-CSRFToken": csrf.csrf_token },
        body: JSON.stringify(payload),
      });
      if (!response.ok) {
        const detail: { error?: string } = await response.json().catch(() => ({}));
        throw new Error(detail.error ?? `Action denied (${response.status})`);
      }
      if (path === "mentions/") {
        setText("");
        nonce.current = crypto.randomUUID();
      }
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Action failed");
    } finally {
      setBusy(false);
    }
  }

  const agent = state?.agents.find((a) => a.id === selected);
  return (
    <aside
      aria-label="Agent teammates"
      className="flex h-full w-[390px] shrink-0 flex-col border-l border-subtle bg-surface-1 text-primary"
    >
      <div className="border-b border-subtle p-4">
        <div className="flex items-center justify-between">
          <h2 className="font-semibold">Study teammates</h2>
          <span role="status" className="text-11 text-tertiary">
            {connection}
          </span>
        </div>
        <p className="mt-1 text-11 text-tertiary">Research drafts need human review.</p>
        <a className="text-11 text-tertiary underline" href="/api/agents/source/">
          Download this prototype's source
        </a>
        <div className="mt-3 flex flex-wrap gap-2">
          {state?.agents.map((a) => (
            <button
              key={a.id}
              type="button"
              aria-pressed={selected === a.id}
              className="rounded border border-subtle px-2 py-1 text-11"
              onClick={() => {
                setSelected(a.id);
                setText(`@${a.name} `);
              }}
            >
              <span aria-hidden="true" className="mr-1 font-semibold">
                {a.avatar}
              </span>
              @{a.name}
            </button>
          ))}
        </div>
      </div>
      <div
        className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4"
        aria-label="Agent activity"
        aria-live="polite"
        aria-relevant="additions"
      >
        {state?.runs.map((run) => {
          const teammate = state.agents.find((a) => a.id === run.agent_id);
          return (
            <section key={run.id} data-run-id={run.id} className="rounded border border-subtle p-3">
              <div className="flex justify-between gap-2 text-13">
                <strong>
                  {teammate?.avatar} {teammate?.name}
                </strong>
                <span data-run-status={run.status}>{run.status.replaceAll("_", " ")}</span>
              </div>
              <p className="font-mono mt-1 text-[10px] break-all text-tertiary">Execution {run.id}</p>
              {state.events
                .filter((e) => e.run_id === run.id)
                .map((e) => (
                  <div key={e.id} data-event-id={e.id} className="mt-3 border-t border-subtle pt-2">
                    <p className="text-[10px] text-tertiary uppercase">
                      {e.actor_id === teammate?.user_id ? teammate.name : `Human ${e.actor_id.slice(0, 8)}`} ·{" "}
                      {e.type.replaceAll("_", " ")} · {new Date(e.at).toLocaleTimeString()}
                    </p>
                    <p className="mt-1 text-11 break-words whitespace-pre-wrap">{e.text}</p>
                  </div>
                ))}
              {state.can_act && run.status === "awaiting_review" && (
                <div className="mt-3 flex gap-2">
                  <button
                    disabled={busy}
                    className="rounded bg-accent-primary px-2 py-1 text-11 text-white"
                    onClick={() => void act(`runs/${run.id}/review/`, { decision: "approve" })}
                  >
                    Approve research draft
                  </button>
                  <button
                    disabled={busy}
                    className="rounded border px-2 py-1 text-11"
                    onClick={() => void act(`runs/${run.id}/review/`, { decision: "reject" })}
                  >
                    Reject
                  </button>
                </div>
              )}
              {state.can_act && ["queued", "running"].includes(run.status) && (
                <button
                  disabled={busy}
                  className="mt-2 text-11 underline"
                  onClick={() => void act(`runs/${run.id}/cancel/`, {})}
                >
                  Cancel run
                </button>
              )}
            </section>
          );
        })}
        {state?.runs.length === 0 && (
          <p className="text-13 text-tertiary">Mention a teammate to start a research draft from this Page.</p>
        )}
      </div>
      <form
        className="border-t border-subtle p-4"
        onSubmit={(e) => {
          e.preventDefault();
          void act("mentions/", { agent_id: selected, text, nonce: nonce.current });
        }}
      >
        <label htmlFor="agent-mention" className="text-11">
          Mention a teammate
        </label>
        <textarea
          id="agent-mention"
          rows={3}
          value={text}
          disabled={!state?.can_act || busy}
          onChange={(e) => setText(e.target.value)}
          placeholder={agent ? `@${agent.name} propose a pricing experiment` : "Connecting to teammates"}
          className="mt-1 w-full resize-none rounded border border-subtle bg-surface-1 p-2 text-13"
        />
        <button
          disabled={!state?.can_act || busy || !agent || !text.includes(`@${agent.name}`)}
          className="mt-2 rounded bg-accent-primary px-3 py-1.5 text-13 text-white disabled:opacity-50"
          type="submit"
        >
          Send mention
        </button>
        {error && (
          <p role="alert" className="mt-2 text-11 text-danger-primary">
            {error}
          </p>
        )}
        <p className="mt-2 text-[10px] text-tertiary">Approval records a draft. Accepted facts stay in the Library.</p>
      </form>
    </aside>
  );
}
