/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */
import { useState } from "react";
import { observer } from "mobx-react";
import useSWR from "swr";
import { API_BASE_URL } from "@plane/constants";
import { Button } from "@plane/propel/button";
import { useProject } from "@/hooks/store/use-project";
import { IssueService } from "@/services/issue/issue.service";
import { CycleService } from "@/services/cycle.service";
import { ModuleService } from "@/services/module.service";
import { ProjectPageService } from "@/services/page/project-page.service";
import { ResearchService } from "@/services/integrations/research.service";
import type { ResearchConnection, ResearchPreview } from "@/services/integrations/research.service";

const service = new ResearchService();
const issueService = new IssueService();
const cycleService = new CycleService();
const moduleService = new ModuleService();
const pageService = new ProjectPageService();
const control = "w-full rounded border border-custom-border-200 bg-custom-background-100 px-3 py-2 text-sm";
const panel = "space-y-4 rounded-lg border border-custom-border-200 p-5";

function message(error: unknown): string {
  const data = (error as { response?: { data?: unknown } })?.response?.data ?? error;
  return typeof data === "string" ? data : JSON.stringify(data) || "The request failed. Please retry.";
}

export const ResearchIntegrations = observer(function ResearchIntegrations({ slug }: { slug: string }) {
  const { workspaceProjectIds, getProjectById } = useProject();
  const [selectedProject, setSelectedProject] = useState("");
  const projectId = selectedProject || workspaceProjectIds?.[0] || "";
  return (
    <div className="text-custom-text-100 mx-auto w-full max-w-5xl space-y-6 p-6">
      <div>
        <h2 className="text-xl font-semibold">Research tools</h2>
        <p className="text-sm text-custom-text-200 mt-1">
          Historical integrations, importers, and AI assistance on current Plane.
        </p>
      </div>
      <label className="text-sm block space-y-2">
        Project
        <select className={control} value={projectId} onChange={(event) => setSelectedProject(event.target.value)}>
          {!projectId && <option value="">Select a project</option>}
          {workspaceProjectIds?.map((id) => (
            <option key={id} value={id}>
              {getProjectById(id)?.name}
            </option>
          ))}
        </select>
      </label>
      {projectId ? (
        <ProjectResearch key={`${slug}/${projectId}`} slug={slug} projectId={projectId} />
      ) : (
        <p>Create a project to use research tools.</p>
      )}
    </div>
  );
});

function ProjectResearch({ slug, projectId }: { slug: string; projectId: string }) {
  const {
    data: connections,
    error,
    mutate,
  } = useSWR(["research-connections", slug, projectId], () => service.connections(slug, projectId));
  const [provider, setProvider] = useState<ResearchConnection["provider"]>("github");
  const [source, setSource] = useState("");
  const [secondary, setSecondary] = useState("");
  const [email, setEmail] = useState("");
  const [token, setToken] = useState("");
  const [secret, setSecret] = useState("");
  const [mapping, setMapping] = useState("{}");
  const [sync, setSync] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const connect = async () => {
    setBusy(true);
    setNotice("");
    try {
      const config =
        provider === "github"
          ? { repository: source, sync }
          : provider === "jira"
            ? { site: source, project_key: secondary }
            : { team_id: source, channel_id: secondary, notify: sync };
      await service.connect(slug, projectId, {
        provider,
        config: { ...JSON.parse(mapping), ...config },
        credentials: { token, email, webhook_secret: secret, signing_secret: secret },
      });
      setToken("");
      setSecret("");
      await mutate();
      setNotice("Connection saved.");
    } catch (failure) {
      setNotice(message(failure));
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      {error && <p role="alert">{message(error)}</p>}
      <section className={panel} aria-label="Connect a provider">
        <h3 className="font-semibold">Connect a provider</h3>
        <form
          className="grid gap-4 sm:grid-cols-2"
          onSubmit={(event) => {
            event.preventDefault();
            void connect();
          }}
        >
          <label className="text-sm space-y-1">
            Provider
            <select
              className={control}
              value={provider}
              onChange={(event) => {
                setProvider(event.target.value as ResearchConnection["provider"]);
                setSource("");
                setSecondary("");
                setToken("");
                setSecret("");
                setSync(false);
                setMapping("{}");
              }}
            >
              <option value="github">GitHub</option>
              <option value="jira">Jira Cloud</option>
              <option value="slack">Slack</option>
            </select>
          </label>
          <label className="text-sm space-y-1">
            {provider === "github"
              ? "Repository (owner/name)"
              : provider === "jira"
                ? "Jira site URL"
                : "Slack team ID"}
            <input className={control} required value={source} onChange={(event) => setSource(event.target.value)} />
          </label>
          {provider !== "github" && (
            <label className="text-sm space-y-1">
              {provider === "jira" ? "Jira project key" : "Slack channel ID"}
              <input
                className={control}
                required
                value={secondary}
                onChange={(event) => setSecondary(event.target.value)}
              />
            </label>
          )}
          {provider === "jira" && (
            <label className="text-sm space-y-1">
              Jira account email
              <input
                type="email"
                className={control}
                required
                value={email}
                onChange={(event) => setEmail(event.target.value)}
              />
            </label>
          )}
          <label className="text-sm space-y-1">
            {provider === "slack" ? "Installed bot token" : "API token"}
            <input
              type="password"
              autoComplete="off"
              className={control}
              required
              value={token}
              onChange={(event) => setToken(event.target.value)}
            />
          </label>
          {provider !== "jira" && (
            <label className="text-sm space-y-1">
              {provider === "github" ? "Webhook secret" : "Slack signing secret"}
              <input
                type="password"
                autoComplete="off"
                className={control}
                required={provider === "slack"}
                value={secret}
                onChange={(event) => setSecret(event.target.value)}
              />
            </label>
          )}
          {provider !== "slack" && (
            <details className="sm:col-span-2">
              <summary className="text-sm cursor-pointer">Field mapping</summary>
              <p className="text-sm text-custom-text-200 my-2">
                Map source status IDs to Plane state IDs with state_map. Map source user IDs to existing project member
                IDs with assignees. Jira also accepts priority_map and estimate_field.
              </p>
              <textarea
                aria-label="Field mapping JSON"
                className={control}
                rows={4}
                value={mapping}
                onChange={(event) => setMapping(event.target.value)}
              />
            </details>
          )}
          {provider !== "jira" && (
            <label className="text-sm flex items-start gap-2 sm:col-span-2">
              <input type="checkbox" checked={sync} onChange={(event) => setSync(event.target.checked)} />
              {provider === "github"
                ? "Enable sync. Export local project issues and EXTERNAL comments. GitHub owns imported content; Plane owns state. Internal comments stay private."
                : "Send project issue notifications to this channel."}
            </label>
          )}
          <Button type="submit" disabled={busy}>
            {busy ? "Connecting…" : "Save connection"}
          </Button>
        </form>
        {notice && (
          <p role="status" className="text-sm">
            {notice}
          </p>
        )}
      </section>
      {connections
        ?.filter((item) => item.active)
        .map((connection) => (
          <ConnectionPanel key={connection.id} {...{ slug, projectId, connection }} onDisconnect={() => mutate()} />
        ))}
      <ResearchAssistant {...{ slug, projectId }} />
      <ResearchAnalytics {...{ slug, projectId }} />
    </>
  );
}

function ConnectionPanel({
  slug,
  projectId,
  connection,
  onDisconnect,
}: {
  slug: string;
  projectId: string;
  connection: ResearchConnection;
  onDisconnect: () => unknown;
}) {
  const [preview, setPreview] = useState<ResearchPreview>();
  const [acknowledged, setAcknowledged] = useState(false);
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const { data: jobs, mutate } = useSWR(
    ["research-jobs", slug, projectId, connection.id],
    () => service.jobs(slug, projectId, connection.id),
    { refreshInterval: 3000 }
  );
  const act = async (action: () => Promise<unknown>) => {
    setBusy(true);
    setNotice("");
    try {
      await action();
      await mutate();
    } catch (error) {
      setNotice(message(error));
    } finally {
      setBusy(false);
    }
  };
  const hook = `${API_BASE_URL || window.location.origin}/api/research/hooks/${connection.id}/${connection.provider}/`;
  return (
    <section className={panel} aria-label={`${connection.provider} connection`}>
      <div className="flex items-center justify-between gap-4">
        <h3 className="font-semibold capitalize">
          {connection.provider}:{" "}
          {String(connection.config.repository ?? connection.config.project_key ?? connection.config.channel_id)}
        </h3>
        <Button
          variant="secondary"
          disabled={busy}
          onClick={() =>
            void act(async () => {
              await service.disconnect(slug, projectId, connection.id);
              onDisconnect();
            })
          }
        >
          Disconnect
        </Button>
      </div>
      {connection.provider !== "jira" && (
        <label className="text-sm block space-y-1">
          {connection.provider === "slack" ? "Slack slash command request URL" : "GitHub webhook payload URL"}
          <input className={control} readOnly value={hook} onFocus={(event) => event.target.select()} />
        </label>
      )}
      {connection.provider !== "slack" && (
        <Button
          variant="secondary"
          disabled={busy}
          onClick={() =>
            void act(async () => {
              setPreview(await service.preview(slug, projectId, connection.id));
              setAcknowledged(false);
            })
          }
        >
          Preview import
        </Button>
      )}
      {preview && (
        <div className="text-sm space-y-3">
          <ul className="list-disc space-y-1 pl-5">
            {preview.limitations.map((text) => (
              <li key={text}>{text}</li>
            ))}
          </ul>
          <div className="overflow-x-auto">
            <table className="w-full text-left">
              <caption className="text-left">
                Source sample{preview.has_more ? " (more issues will be imported)" : ""}
              </caption>
              <thead>
                <tr>
                  <th>Source</th>
                  <th>Issue</th>
                  <th>State</th>
                  <th>Points</th>
                </tr>
              </thead>
              <tbody>
                {preview.sample.map((row) => (
                  <tr key={row.id}>
                    <td className="p-2">{row.key}</td>
                    <td>{row.title}</td>
                    <td>{row.state_name}</td>
                    <td>{row.estimate ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <label className="flex gap-2">
            <input type="checkbox" checked={acknowledged} onChange={(event) => setAcknowledged(event.target.checked)} />
            I accept these import limitations.
          </label>
          <Button
            disabled={!acknowledged || busy}
            onClick={() =>
              void act(async () => {
                await service.start(slug, projectId, connection.id);
                setNotice("Import queued.");
              })
            }
          >
            Start import
          </Button>
        </div>
      )}
      {notice && (
        <p role="status" className="text-sm">
          {notice}
        </p>
      )}
      <ul className="text-sm space-y-2">
        {jobs?.map((job) => (
          <li key={job.id} className="border-custom-border-200 rounded border p-3">
            <span>
              {job.operation}: {job.status} · {job.processed} processed
            </span>
            {job.error && <p role="alert">{job.error}</p>}
            {job.status !== "completed" && (
              <Button
                variant="secondary"
                disabled={busy}
                onClick={() => void act(() => service.retry(slug, projectId, job.id))}
              >
                Resume
              </Button>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}

function ResearchAssistant({ slug, projectId }: { slug: string; projectId: string }) {
  const { data: pages, error: pagesError } = useSWR(["research-pages", slug, projectId], () =>
    pageService.fetchAll(slug, projectId)
  );
  const [action, setAction] = useState("Draft an issue");
  const [prompt, setPrompt] = useState("");
  const [pageId, setPageId] = useState("");
  const [draft, setDraft] = useState("");
  const [title, setTitle] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const generate = async () => {
    setBusy(true);
    setNotice("");
    setDraft("");
    try {
      const context = prompt;
      if (action !== "Page to issue" && !context.trim())
        throw new Error("Enter source text or choose a page with content.");
      const response = await service.assist(
        slug,
        projectId,
        action === "Page to issue" ? "Draft one actionable issue from these page notes" : action,
        context,
        action === "Page to issue" ? pageId : undefined
      );
      setDraft(response.response);
      setTitle(response.response.split("\n")[0].slice(0, 255));
    } catch (error) {
      setNotice(error instanceof Error ? error.message : message(error));
    } finally {
      setBusy(false);
    }
  };
  const accept = async () => {
    setBusy(true);
    setNotice("");
    try {
      const html = new Option(draft).innerHTML.replace(/\n/g, "<br/>");
      const issue = await issueService.createIssue(slug, projectId, {
        name: title,
        description_html: `<p>${html}</p>`,
      });
      setNotice(`Created issue ${issue.sequence_id}.`);
      setDraft("");
    } catch (error) {
      setNotice(message(error));
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className={panel} aria-label="Research assistant">
      <h3 className="font-semibold">AI assistance</h3>
      <label className="text-sm block space-y-1">
        Action
        <select className={control} value={action} onChange={(event) => setAction(event.target.value)}>
          {["Draft an issue", "Rewrite", "Summarize", "Page to issue"].map((value) => (
            <option key={value}>{value}</option>
          ))}
        </select>
      </label>
      {action === "Page to issue" ? (
        <label className="text-sm block space-y-1">
          Page
          <select className={control} value={pageId} onChange={(event) => setPageId(event.target.value)}>
            <option value="">Select a page</option>
            {pages?.map((page) => (
              <option key={page.id} value={page.id}>
                {page.name}
              </option>
            ))}
          </select>
          {pagesError && <span role="alert">{message(pagesError)}</span>}
        </label>
      ) : (
        <label className="text-sm block space-y-1">
          Source text
          <textarea className={control} rows={4} value={prompt} onChange={(event) => setPrompt(event.target.value)} />
        </label>
      )}
      <Button disabled={busy || !(action === "Page to issue" ? pageId : prompt)} onClick={() => void generate()}>
        Generate draft
      </Button>
      {draft && (
        <div className="space-y-3">
          <label className="text-sm block">
            Issue title
            <input
              className={control}
              maxLength={255}
              value={title}
              onChange={(event) => setTitle(event.target.value)}
            />
          </label>
          <label className="text-sm block">
            Review and edit the draft
            <textarea className={control} rows={8} value={draft} onChange={(event) => setDraft(event.target.value)} />
          </label>
          <Button disabled={busy || !title.trim()} onClick={() => void accept()}>
            Accept and create issue
          </Button>
        </div>
      )}
      {notice && (
        <p role="status" className="text-sm">
          {notice}
        </p>
      )}
    </section>
  );
}

function ResearchAnalytics({ slug, projectId }: { slug: string; projectId: string }) {
  const [group, setGroup] = useState("state__name");
  const [cycleId, setCycleId] = useState("");
  const [moduleId, setModuleId] = useState("");
  const [stateGroup, setStateGroup] = useState("");
  const { data: cycles } = useSWR(["research-cycles", slug, projectId], () =>
    cycleService.getCyclesWithParams(slug, projectId)
  );
  const { data: modules } = useSWR(["research-modules", slug, projectId], () =>
    moduleService.getModules(slug, projectId)
  );
  const query = new URLSearchParams({
    group_by: group,
    ...(cycleId && { cycle_id: cycleId }),
    ...(moduleId && { module_id: moduleId }),
    ...(stateGroup && { state_group: stateGroup }),
  }).toString();
  const { data, error } = useSWR(
    ["research-summary", slug, projectId, query],
    () => service.summary(slug, projectId, query),
    { refreshInterval: 5000 }
  );
  return (
    <section className={panel} aria-label="Research analytics">
      <h3 className="font-semibold">Research analytics</h3>
      <div className="text-sm flex flex-wrap items-center gap-4">
        <label>
          Group by{" "}
          <select className={control} value={group} onChange={(event) => setGroup(event.target.value)}>
            <option value="state__name">State</option>
            <option value="priority">Priority</option>
          </select>
        </label>
        <label>
          Cycle
          <select className={control} value={cycleId} onChange={(event) => setCycleId(event.target.value)}>
            <option value="">All cycles</option>
            {cycles?.map((cycle) => (
              <option key={cycle.id} value={cycle.id}>
                {cycle.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Module
          <select className={control} value={moduleId} onChange={(event) => setModuleId(event.target.value)}>
            <option value="">All modules</option>
            {modules?.map((module) => (
              <option key={module.id} value={module.id}>
                {module.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          State group
          <select className={control} value={stateGroup} onChange={(event) => setStateGroup(event.target.value)}>
            <option value="">All state groups</option>
            {["backlog", "unstarted", "started", "completed", "cancelled"].map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </label>
        <a
          className="text-custom-primary-100 underline"
          href={`${API_BASE_URL}${service.root(slug, projectId)}summary/?${query}&export=csv`}
        >
          Download CSV
        </a>
        <a className="text-custom-primary-100 underline" href={`/${slug}/projects/${projectId}/issues/`}>
          Open work items and Timeline
        </a>
      </div>
      {error && <p role="alert">{message(error)}</p>}
      {data && (
        <>
          <p className="text-sm">
            {data.count} issues · {data.estimate_points} estimate points · {data.comments} comments
          </p>
          <table className="text-sm w-full text-left">
            <thead>
              <tr>
                <th>Group</th>
                <th>Issues</th>
                <th>Estimate points</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(data.groups).map(([name, values]) => (
                <tr key={name}>
                  <td className="py-2">{name}</td>
                  <td>{values.count}</td>
                  <td>{values.estimate_points}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </section>
  );
}
