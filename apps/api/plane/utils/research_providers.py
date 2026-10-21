# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Provider APIs only. No Plane database or worker policy lives in this module."""

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from plane.utils.research import decrypt_credentials


IMPORT_LIMITATIONS = [
    "Source users must map to existing project members; no invitations are sent.",
    "Attachments remain source links; binary files and source permissions are not copied.",
    "Rich descriptions become plain text; custom fields other than the selected estimate are omitted.",
    "Relationships outside the imported project and historical change logs are not copied.",
    "Jira imports Blocks, Duplicate and Relates links; custom relationship types are omitted.",
]


def document_text(value):
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        text = value.get("text", "") + "".join(document_text(item) for item in value.get("content", []))
        return text + ("\n" if value.get("type") in ("paragraph", "heading", "listItem") else "")
    return ""


def jira_relationships(links):
    relations = []
    for link in links:
        kind = (link.get("type") or {}).get("name", "").lower()
        outward = link.get("outwardIssue")
        target = outward or link.get("inwardIssue")
        relation = {
            "blocks": "blocking" if outward else "blocked_by",
            "duplicate": "duplicate",
            "relates": "relates_to",
        }.get(kind)
        if target and relation:
            relations.append({"key": target["key"], "type": relation})
    return relations


class Provider:
    def __init__(self, connection):
        self.connection = connection
        self.config = connection.config
        self.credentials = decrypt_credentials(connection)
        self.session = requests.Session()
        self.session.mount(
            "https://",
            HTTPAdapter(
                max_retries=Retry(
                    total=3,
                    backoff_factor=1,
                    status_forcelist=[429, 502, 503, 504],
                    allowed_methods=["GET"],
                    respect_retry_after_header=False,
                )
            ),
        )
        if connection.provider == "github":
            self.base_url = "https://api.github.com"
            self.session.headers.update(
                {
                    "Authorization": f"Bearer {self.credentials['token']}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                }
            )
        elif connection.provider == "jira":
            self.base_url = self.config["site"] + "/rest/api/3"
            self.session.auth = (self.credentials["email"], self.credentials["token"])
        else:
            self.base_url = "https://slack.com/api"
            self.session.headers["Authorization"] = f"Bearer {self.credentials['token']}"

    def request(self, method, path, **kwargs):
        response = self.session.request(method, self.base_url + path, timeout=(10, 30), allow_redirects=False, **kwargs)
        if 300 <= response.status_code < 400:
            raise ValueError("Provider redirected the request; update the installation")
        if method == "DELETE" and response.status_code == 404:
            return {}
        response.raise_for_status()
        if response.status_code == 204:
            return {}
        result = response.json()
        if isinstance(result, dict) and result.get("ok") is False:
            raise ValueError("Provider rejected the operation")
        return result

    def issue_page(self, cursor):
        if self.connection.provider == "github":
            page = cursor.get("page", 1)
            rows = self.request(
                "GET",
                f"/repos/{self.config['repository']}/issues",
                params={
                    "state": "all",
                    "sort": "created",
                    "direction": "asc",
                    "per_page": 100,
                    "page": page,
                },
            )
            return [self.github_issue(row) for row in rows if "pull_request" not in row], (
                {"page": page + 1} if len(rows) == 100 else None
            )
        fields = [
            "summary",
            "description",
            "status",
            "priority",
            "assignee",
            "labels",
            "duedate",
            "parent",
            "issuelinks",
            "attachment",
        ]
        if self.config.get("estimate_field"):
            fields.append(self.config["estimate_field"])
        params = {
            "jql": f"project = {self.config['project_key']} ORDER BY key ASC",
            "maxResults": 100,
            "fields": ",".join(fields),
        }
        if cursor.get("nextPageToken"):
            params["nextPageToken"] = cursor["nextPageToken"]
        data = self.request("GET", "/search/jql", params=params)
        if data.get("isLast") is False and not data.get("nextPageToken"):
            raise ValueError("Jira did not provide a continuation token")
        return [self.jira_issue(row) for row in data["issues"]], (
            {"nextPageToken": data["nextPageToken"]} if data.get("nextPageToken") else None
        )

    def github_issue(self, row):
        closed = row["state"] == "closed"
        return {
            "id": str(row["id"]),
            "number": row["number"],
            "key": str(row["number"]),
            "title": row["title"],
            "description": row.get("body") or "",
            "url": row["html_url"],
            "state_id": row["state"],
            "state_name": "Cancelled"
            if closed and row.get("state_reason") == "not_planned"
            else "Done"
            if closed
            else "Todo",
            "group": "cancelled"
            if closed and row.get("state_reason") == "not_planned"
            else "completed"
            if closed
            else "unstarted",
            "labels": [label["name"] for label in row.get("labels", [])],
            "assignees": [str(user["id"]) for user in row.get("assignees", [])],
            "priority": "none",
            "estimate": None,
            "due_date": None,
            "parent": None,
            "relations": [],
            "attachments": [],
        }

    def jira_issue(self, row):
        fields = row["fields"]
        state = fields.get("status") or {}
        source_priority = fields.get("priority") or {}
        priority_name = source_priority.get("name", "none")
        priority_map = self.config.get("priority_map", {})
        return {
            "id": str(row["id"]),
            "key": row["key"],
            "number": row["key"],
            "title": fields["summary"],
            "description": document_text(fields.get("description")),
            "url": self.config["site"] + "/browse/" + row["key"],
            "state_id": state.get("id", ""),
            "state_name": state.get("name", "Todo"),
            "group": {"done": "completed", "indeterminate": "started"}.get(
                (state.get("statusCategory") or {}).get("key"), "unstarted"
            ),
            "priority": priority_map.get(
                str(source_priority.get("id", "")),
                priority_map.get(
                    priority_name,
                    {"Highest": "urgent", "High": "high", "Medium": "medium", "Low": "low", "Lowest": "low"}.get(
                        priority_name, "none"
                    ),
                ),
            ),
            "estimate": fields.get(self.config.get("estimate_field", "")),
            "due_date": fields.get("duedate"),
            "labels": fields.get("labels", []),
            "assignees": [fields["assignee"]["accountId"]] if fields.get("assignee") else [],
            "parent": (fields.get("parent") or {}).get("key"),
            "relations": jira_relationships(fields.get("issuelinks", [])),
            "attachments": [{"url": a["content"], "name": a["filename"]} for a in fields.get("attachment", [])],
        }

    def comments(self, item):
        if self.connection.provider == "github":
            page = 1
            while True:
                rows = self.request(
                    "GET",
                    f"/repos/{self.config['repository']}/issues/{item['number']}/comments",
                    params={"per_page": 100, "page": page},
                )
                for row in rows:
                    yield {
                        "id": str(row["id"]),
                        "text": row.get("body", ""),
                        "author": (row.get("user") or {}).get("login", "Source user"),
                    }
                if len(rows) < 100:
                    return
                page += 1
        else:
            start = 0
            while True:
                data = self.request(
                    "GET", f"/issue/{item['key']}/comment", params={"startAt": start, "maxResults": 100}
                )
                for row in data["comments"]:
                    yield {
                        "id": str(row["id"]),
                        "text": document_text(row["body"]),
                        "author": (row.get("author") or {}).get("displayName", "Source user"),
                    }
                start += len(data["comments"])
                if start >= data["total"] or not data["comments"]:
                    return
