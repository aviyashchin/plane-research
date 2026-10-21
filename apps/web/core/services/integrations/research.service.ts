/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */
import { API_BASE_URL } from "@plane/constants";
import { APIService } from "@/services/api.service";

export type ResearchConnection = {
  id: string;
  provider: "github" | "jira" | "slack";
  active: boolean;
  config: Record<string, unknown>;
};
export type ResearchJob = { id: string; status: string; operation: string; processed: number; error: string };
export type ResearchPreview = {
  sample: {
    id: string;
    key: string;
    title: string;
    state_name: string;
    estimate: number | null;
    assignees: string[];
  }[];
  has_more: boolean;
  limitations: string[];
};
export type ResearchSummary = {
  count: number;
  estimate_points: number;
  comments: number;
  groups: Record<string, { count: number; estimate_points: number }>;
};

export class ResearchService extends APIService {
  constructor() {
    super(API_BASE_URL);
  }
  root(slug: string, projectId: string) {
    return `/api/workspaces/${slug}/projects/${projectId}/research/`;
  }
  async connections(slug: string, projectId: string): Promise<ResearchConnection[]> {
    return (await this.get(this.root(slug, projectId) + "connections/")).data;
  }
  async connect(slug: string, projectId: string, data: object): Promise<ResearchConnection> {
    return (await this.post(this.root(slug, projectId) + "connections/", data)).data;
  }
  async disconnect(slug: string, projectId: string, id: string) {
    await this.delete(this.root(slug, projectId) + `connections/${id}/`);
  }
  async preview(slug: string, projectId: string, id: string): Promise<ResearchPreview> {
    return (await this.post(this.root(slug, projectId) + `connections/${id}/imports/`, { action: "preview" })).data;
  }
  async start(slug: string, projectId: string, id: string): Promise<ResearchJob> {
    return (
      await this.post(this.root(slug, projectId) + `connections/${id}/imports/`, { acknowledge_unsupported: true })
    ).data;
  }
  async jobs(slug: string, projectId: string, id: string): Promise<ResearchJob[]> {
    return (await this.get(this.root(slug, projectId) + `connections/${id}/imports/`)).data;
  }
  async retry(slug: string, projectId: string, id: string) {
    await this.post(this.root(slug, projectId) + `jobs/${id}/retry/`);
  }
  async summary(slug: string, projectId: string, query: string): Promise<ResearchSummary> {
    return (await this.get(this.root(slug, projectId) + `summary/?${query}`)).data;
  }
  async assist(
    slug: string,
    projectId: string,
    task: string,
    prompt: string,
    pageId?: string
  ): Promise<{ response: string }> {
    return (
      await this.post(`/api/workspaces/${slug}/projects/${projectId}/ai-assistant/`, { task, prompt, page_id: pageId })
    ).data;
  }
}
