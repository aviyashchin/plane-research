# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import pytest
from plane.db.models import Project, ProjectMember


@pytest.fixture
def research_project(workspace, create_user, settings):
    settings.WEB_URL = "http://localhost:3000"
    project = Project.objects.create(name="Research", identifier="RES", workspace=workspace)
    ProjectMember.objects.create(project=project, member=create_user, role=20)
    return project


@pytest.mark.contract
@pytest.mark.django_db
def test_admin_can_connect_without_disclosing_credentials(session_client, workspace, research_project, monkeypatch):
    from cryptography.fernet import Fernet

    monkeypatch.setenv("RESEARCH_CREDENTIAL_KEY", Fernet.generate_key().decode())
    url = f"/api/workspaces/{workspace.slug}/projects/{research_project.id}/research/connections/"
    response = session_client.post(
        url,
        {
            "provider": "github",
            "config": {"repository": "makeplane/plane"},
            "credentials": {"token": "secret-fixture", "webhook_secret": "secret-signature"},
        },
        format="json",
    )
    assert response.status_code == 201
    assert "secret-fixture" not in str(response.data)
    assert "secret-signature" not in str(session_client.get(url).data)
    assert session_client.get(url).data[0]["config"]["repository"] == "makeplane/plane"


@pytest.mark.contract
@pytest.mark.django_db
def test_jira_import_replay_preserves_twelve_issues_six_closed_and_thirty_points(
    session_client,
    workspace,
    research_project,
    monkeypatch,
):
    from cryptography.fernet import Fernet
    from unittest.mock import Mock

    monkeypatch.setenv("RESEARCH_CREDENTIAL_KEY", Fernet.generate_key().decode())
    root = f"/api/workspaces/{workspace.slug}/projects/{research_project.id}/"
    connection = session_client.post(
        root + "research/connections/",
        {
            "provider": "jira",
            "config": {
                "site": "https://research.atlassian.net",
                "project_key": "RES",
                "estimate_field": "customfield_10016",
            },
            "credentials": {"token": "fixture", "email": "research@example.com"},
        },
        format="json",
    ).data
    payload = {
        "isLast": True,
        "issues": [
            {
                "id": str(i),
                "key": f"RES-{i}",
                "fields": {
                    "summary": f"Research {i}",
                    "description": {"type": "doc", "content": [{"type": "text", "text": "Notes"}]},
                    "status": {
                        "id": "done" if i <= 6 else "todo",
                        "name": "Done" if i <= 6 else "Todo",
                        "statusCategory": {"key": "done" if i <= 6 else "new"},
                    },
                    "labels": ["research"],
                    "priority": {"name": "High"},
                    "customfield_10016": 2 if i % 2 else 3,
                },
            }
            for i in range(1, 13)
        ],
    }

    def provider_request(self, method, url, **kwargs):
        response = Mock(status_code=200)
        response.json.return_value = (
            {
                "comments": [
                    {"id": "c-" + url.split("/")[-2], "body": "Reviewed", "author": {"displayName": "Reviewer"}}
                ],
                "total": 1,
            }
            if url.endswith("/comment")
            else payload
        )
        response.raise_for_status.return_value = None
        return response

    monkeypatch.setattr("requests.Session.request", provider_request)
    imports = root + f"research/connections/{connection['id']}/imports/"
    preview = session_client.post(imports, {"action": "preview"}, format="json")
    assert preview.status_code == 200
    job = session_client.post(imports, {"acknowledge_unsupported": True}, format="json")
    assert job.status_code == 202
    from plane.bgtasks.research_task import run_research_job

    run_research_job.apply(args=[job.data["id"]], throw=True)
    run_research_job.apply(args=[job.data["id"]], throw=True)
    result = session_client.get(imports).data[0]
    assert result["status"] == "completed"
    assert result["processed"] == 12
    stats = session_client.get(root + "advance-analytics/").data
    assert stats["total_work_items"]["count"] == 12
    assert stats["completed_work_items"]["count"] == 6
    summary = session_client.get(root + "research/summary/").data
    assert summary["estimate_points"] == 30
    assert summary["comments"] == 12


@pytest.mark.contract
@pytest.mark.django_db
def test_slack_signature_replay_and_project_mapping(session_client, workspace, research_project, monkeypatch):
    import hashlib
    import hmac
    import time
    from cryptography.fernet import Fernet
    from rest_framework.test import APIClient

    monkeypatch.setenv("RESEARCH_CREDENTIAL_KEY", Fernet.generate_key().decode())
    root = f"/api/workspaces/{workspace.slug}/projects/{research_project.id}/research/"
    connection = session_client.post(
        root + "connections/",
        {
            "provider": "slack",
            "config": {"team_id": "T123", "channel_id": "C123", "notify": False},
            "credentials": {"token": "fixture", "signing_secret": "signature-fixture"},
        },
        format="json",
    ).data
    timestamp = str(int(time.time()))
    body = "team_id=T123&channel_id=C123&text=Research+from+Slack"
    signature = "v0=" + hmac.new(b"signature-fixture", f"v0:{timestamp}:{body}".encode(), hashlib.sha256).hexdigest()
    client = APIClient()
    hook = f"/api/research/hooks/{connection['id']}/slack/"
    assert client.post(hook, body, content_type="application/x-www-form-urlencoded").status_code == 403
    for _ in range(2):
        assert (
            client.post(
                hook,
                body,
                content_type="application/x-www-form-urlencoded",
                HTTP_X_SLACK_REQUEST_TIMESTAMP=timestamp,
                HTTP_X_SLACK_SIGNATURE=signature,
            ).status_code
            == 200
        )
    jobs = session_client.get(root + f"connections/{connection['id']}/imports/").data
    assert len(jobs) == 1
    from plane.bgtasks.research_task import run_research_job

    run_research_job.apply(args=[jobs[0]["id"]], throw=True)
    run_research_job.apply(args=[jobs[0]["id"]], throw=True)
    assert session_client.get(root + "summary/").data["count"] == 1


@pytest.mark.contract
@pytest.mark.django_db
def test_source_identity_and_configuration_types(session_client, workspace, research_project, monkeypatch):
    from cryptography.fernet import Fernet

    monkeypatch.setenv("RESEARCH_CREDENTIAL_KEY", Fernet.generate_key().decode())
    url = f"/api/workspaces/{workspace.slug}/projects/{research_project.id}/research/connections/"
    data = {"provider": "github", "config": {"repository": "owner/first"}, "credentials": {"token": "fixture"}}
    assert session_client.post(url, data, format="json").status_code == 201
    data["config"]["repository"] = "owner/second"
    assert session_client.post(url, data, format="json").status_code == 400
    data["config"] = {"repository": "owner/first", "sync": "false"}
    assert session_client.post(url, data, format="json").status_code == 400


@pytest.mark.contract
@pytest.mark.django_db
def test_github_state_dates_comment_privacy_and_replay(session_client, workspace, research_project, monkeypatch):
    import hashlib
    import hmac
    import json
    from unittest.mock import Mock
    from cryptography.fernet import Fernet
    from rest_framework.test import APIClient
    from plane.db.models import Issue, State, ResearchJob, ResearchObject
    from plane.bgtasks.research_task import run_research_job

    monkeypatch.setenv("RESEARCH_CREDENTIAL_KEY", Fernet.generate_key().decode())
    root = f"/api/workspaces/{workspace.slug}/projects/{research_project.id}/"
    connection = session_client.post(
        root + "research/connections/",
        {
            "provider": "github",
            "config": {"repository": "owner/research", "sync": True},
            "credentials": {"token": "fixture", "webhook_secret": "hook"},
        },
        format="json",
    ).data
    rows = [
        {
            "id": 900,
            "number": 1,
            "title": "Interview buyers",
            "body": "Notes",
            "state": "open",
            "html_url": "https://github.com/owner/research/issues/1",
        }
    ]
    comments, writes = [], []

    def transport(self, method, url, **kwargs):
        response = Mock(status_code=200)
        if method == "GET":
            result = comments if url.endswith("/comments") else rows
        else:
            writes.append((method, url, kwargs["json"]))
            if url.endswith("/comments"):
                result = {"id": 1001, "body": kwargs["json"]["body"], "user": {"login": "plane"}}
                comments.append(result)
            else:
                rows[0].update(kwargs["json"])
                result = rows[0]
        response.json.return_value = result
        return response

    monkeypatch.setattr("requests.Session.request", transport)
    imports = root + f"research/connections/{connection['id']}/imports/"
    job = session_client.post(imports, {"acknowledge_unsupported": True}, format="json").data
    run_research_job.apply(args=[job["id"]], throw=True)
    issue = Issue.objects.get(project=research_project)
    done = State.objects.create(project=research_project, name="Done", group="completed", color="#000000")
    issue_url = root + f"issues/{issue.id}/"
    response = session_client.patch(
        issue_url,
        {
            "state": str(done.id),
            "start_date": "2026-10-20",
            "target_date": "2026-10-25",
        },
        format="json",
    )
    assert response.status_code == 204
    for access, text in [("EXTERNAL", "Public note"), ("INTERNAL", "Private note")]:
        response = session_client.post(
            root + f"issues/{issue.id}/comments/",
            {
                "comment_html": f"<p>{text}</p>",
                "access": access,
            },
            format="json",
        )
        assert response.status_code == 201
    client = APIClient()
    hook = f"/api/research/hooks/{connection['id']}/github/"
    body = json.dumps({"repository": {"full_name": "owner/research"}})
    signature = "sha256=" + hmac.new(b"hook", body.encode(), hashlib.sha256).hexdigest()
    for _ in range(2):
        response = client.post(
            hook,
            body,
            content_type="application/json",
            HTTP_X_HUB_SIGNATURE_256=signature,
            HTTP_X_GITHUB_DELIVERY="fixture-delivery",
            HTTP_X_GITHUB_EVENT="issues",
        )
        assert response.status_code == 200
    sync = ResearchJob.objects.get(delivery_id="fixture-delivery")
    run_research_job.apply(args=[str(sync.id)], throw=True)
    assert ResearchJob.objects.get(id=sync.id).status == "completed"
    assert rows[0]["state"] == "closed"
    assert len(comments) == 1 and "Public note" in comments[0]["body"]
    assert "Private note" not in str(writes)
    saved = session_client.get(issue_url).data
    assert saved["start_date"] == "2026-10-20" and saved["target_date"] == "2026-10-25"
    assert str(saved["state_id"]) == str(done.id)
    ResearchObject.objects.filter(kind="outbound_comment").delete()
    replay = ResearchJob.objects.create(project=research_project, connection_id=connection["id"], operation="sync")
    run_research_job.apply(args=[str(replay.id)], throw=True)
    assert len(comments) == 1
    assert Issue.objects.filter(project=research_project).count() == 1
    foreign = root.replace(workspace.slug, "foreign-workspace") + "research/connections/"
    assert session_client.get(foreign).status_code in (403, 404)


@pytest.mark.contract
@pytest.mark.django_db
def test_failed_import_resumes_after_committed_issue(session_client, workspace, research_project, monkeypatch):
    from unittest.mock import Mock
    from cryptography.fernet import Fernet
    from plane.db.models import Issue, ResearchJob
    from plane.bgtasks.research_task import run_research_job

    monkeypatch.setenv("RESEARCH_CREDENTIAL_KEY", Fernet.generate_key().decode())
    root = f"/api/workspaces/{workspace.slug}/projects/{research_project.id}/research/"
    connection = session_client.post(
        root + "connections/",
        {
            "provider": "github",
            "config": {"repository": "owner/recovery"},
            "credentials": {"token": "fixture"},
        },
        format="json",
    ).data
    rows = [
        {
            "id": i,
            "number": i,
            "title": f"Research {i}",
            "body": "Notes",
            "state": "open",
            "html_url": f"https://github.com/owner/recovery/issues/{i}",
        }
        for i in (1, 2)
    ]
    failing = True

    def transport(self, method, url, **kwargs):
        if failing and url.endswith("/2/comments"):
            raise ValueError("Simulated worker interruption")
        response = Mock(status_code=200)
        response.json.return_value = [] if url.endswith("/comments") else rows
        return response

    monkeypatch.setattr("requests.Session.request", transport)
    job = session_client.post(
        root + f"connections/{connection['id']}/imports/",
        {
            "acknowledge_unsupported": True,
        },
        format="json",
    ).data
    run_research_job.apply(args=[job["id"]], throw=True)
    saved = ResearchJob.objects.get(id=job["id"])
    assert saved.status == "failed" and saved.processed == 1
    assert Issue.objects.filter(project=research_project).count() == 1
    failing = False
    assert session_client.post(root + f"jobs/{saved.id}/retry/", {}, format="json").status_code == 202
    run_research_job.apply(args=[job["id"]], throw=True)
    saved.refresh_from_db()
    assert saved.status == "completed" and saved.processed == 2
    assert Issue.objects.filter(project=research_project).count() == 2


@pytest.fixture
def github_research_source(session_client, workspace, research_project, monkeypatch):
    """Exercise native import jobs against a stateful GitHub HTTP boundary."""
    import json
    from copy import deepcopy
    from urllib.parse import urlparse

    import requests
    from cryptography.fernet import Fernet
    from plane.bgtasks.research_task import run_research_job
    from plane.db.models import State

    monkeypatch.setenv("RESEARCH_CREDENTIAL_KEY", Fernet.generate_key().decode())
    State.objects.create(project=research_project, name="Todo", group="unstarted", color="#000000")
    root = f"/api/workspaces/{workspace.slug}/projects/{research_project.id}/"
    response = session_client.post(
        root + "research/connections/",
        {
            "provider": "github",
            "config": {"repository": "owner/research", "sync": True},
            "credentials": {"token": "fixture"},
        },
        format="json",
    )
    assert response.status_code == 201
    source = {"issues": [], "comments": {}, "writes": []}

    def transport(self, method, url, **kwargs):
        path = urlparse(url).path
        result, status = None, 200
        if method == "GET" and path.endswith("/issues"):
            result = source["issues"]
        elif method == "GET" and path.endswith("/comments"):
            result = list(source["comments"].values())
        else:
            data = kwargs.get("json", {})
            source["writes"].append((method, path, deepcopy(data)))
            if method == "POST" and path.endswith("/issues"):
                number = len(source["issues"]) + 1
                result = {
                    "id": 900 + number,
                    "number": number,
                    "state": "open",
                    "html_url": f"https://github.com/owner/research/issues/{number}",
                    **data,
                }
                source["issues"].append(result)
            elif method == "POST" and path.endswith("/comments"):
                comment_id = str(1001 + len(source["comments"]))
                result = {"id": int(comment_id), "user": {"login": "plane"}, **data}
                source["comments"][comment_id] = result
            elif "/issues/comments/" in path:
                comment_id = path.rsplit("/", 1)[1]
                if method == "DELETE":
                    source["comments"].pop(comment_id)
                    status = 204
                elif method == "PATCH":
                    source["comments"][comment_id].update(data)
                    result = source["comments"][comment_id]
                else:
                    raise AssertionError(f"Unexpected GitHub request: {method} {path}")
            elif method == "PATCH":
                result = next(row for row in source["issues"] if str(row["number"]) == path.rsplit("/", 1)[1])
                result.update(data)
            else:
                raise AssertionError(f"Unexpected GitHub request: {method} {path}")
        response = requests.Response()
        response.status_code = status
        response._content = json.dumps(deepcopy(result)).encode() if status != 204 else b""
        response.url = url
        return response

    monkeypatch.setattr("requests.Session.request", transport)
    imports = root + f"research/connections/{response.data['id']}/imports/"

    def sync():
        job = session_client.post(imports, {"acknowledge_unsupported": True}, format="json")
        assert job.status_code == 202
        run_research_job.apply(args=[job.data["id"]], throw=True)
        saved = next(row for row in session_client.get(imports).data if row["id"] == job.data["id"])
        assert saved["status"] == "completed", saved["error"]

    return root, source, sync


@pytest.mark.contract
@pytest.mark.django_db
def test_github_export_preserves_native_rich_issue(session_client, github_research_source):
    root, source, sync = github_research_source
    html = (
        '<p><strong>Research evidence</strong> <a href="https://example.com/notes">Read notes</a></p>'
        "<table><tbody><tr><td>Buyer A</td><td>Choice B</td></tr></tbody></table>"
    )
    created = session_client.post(
        root + "issues/", {"name": "Native research", "description_html": html}, format="json"
    )
    assert created.status_code == 201
    issue_url = root + f"issues/{created.data['id']}/"
    before = session_client.get(issue_url).data["description_html"]
    assert "<strong>" in before and "<table>" in before and 'href="https://example.com/notes"' in before
    sync()
    sync()
    assert session_client.get(issue_url).data["description_html"] == before
    assert len(source["issues"]) == 1


@pytest.mark.contract
@pytest.mark.django_db
def test_github_comment_edits_and_deletions_sync_in_both_directions(
    session_client, research_project, github_research_source
):
    from plane.db.models import Issue

    root, source, sync = github_research_source
    source["issues"].append(
        {
            "id": 900,
            "number": 1,
            "title": "Interview buyers",
            "body": "Research notes",
            "state": "open",
            "html_url": "https://github.com/owner/research/issues/1",
        }
    )
    source["comments"]["600"] = {"id": 600, "body": "Source note", "user": {"login": "researcher"}}
    sync()
    issue = Issue.objects.get(project=research_project)
    comments_url = root + f"issues/{issue.id}/comments/"
    imported = session_client.get(comments_url)
    assert imported.status_code == 200
    assert "Source note" in str(imported.data)
    source["comments"]["600"]["body"] = "Revised source note"
    sync()
    assert "Revised source note" in str(session_client.get(comments_url).data)

    created = session_client.post(
        comments_url, {"comment_html": "<p>Plane note</p>", "access": "EXTERNAL"}, format="json"
    )
    assert created.status_code == 201
    sync()
    outbound_id = next(key for key, row in source["comments"].items() if "Plane note" in row["body"])
    comment_url = comments_url + f"{created.data['id']}/"
    edited = session_client.patch(comment_url, {"comment_html": "<p>Revised Plane note</p>"}, format="json")
    assert edited.status_code == 200
    sync()
    assert "Revised Plane note" in source["comments"][outbound_id]["body"]
    assert len(source["comments"]) == 2

    source["comments"].pop("600")
    sync()
    assert "Revised source note" not in str(session_client.get(comments_url).data)
    assert session_client.delete(comment_url).status_code == 204
    sync()
    sync()
    assert source["comments"] == {}


@pytest.mark.contract
@pytest.mark.django_db
def test_jira_blocks_and_duplicate_links_keep_their_native_directions(
    session_client, workspace, research_project, monkeypatch
):
    import json

    import requests
    from cryptography.fernet import Fernet
    from plane.bgtasks.research_task import run_research_job
    from plane.db.models import Issue

    monkeypatch.setenv("RESEARCH_CREDENTIAL_KEY", Fernet.generate_key().decode())
    root = f"/api/workspaces/{workspace.slug}/projects/{research_project.id}/"
    connection = session_client.post(
        root + "research/connections/",
        {
            "provider": "jira",
            "config": {"site": "https://research.atlassian.net", "project_key": "RES"},
            "credentials": {"token": "fixture", "email": "research@example.com"},
        },
        format="json",
    )
    assert connection.status_code == 201
    rows = [
        {"id": str(i), "key": f"RES-{i}", "fields": {"summary": f"Research {i}", "issuelinks": []}} for i in (1, 2, 3)
    ]
    rows[0]["fields"]["issuelinks"] = [
        {"type": {"name": "Blocks"}, "outwardIssue": {"key": "RES-2"}},
        {"type": {"name": "Duplicate"}, "outwardIssue": {"key": "RES-3"}},
    ]
    rows[1]["fields"]["issuelinks"] = [{"type": {"name": "Blocks"}, "inwardIssue": {"key": "RES-1"}}]
    rows[2]["fields"]["issuelinks"] = [{"type": {"name": "Duplicate"}, "inwardIssue": {"key": "RES-1"}}]

    def transport(self, method, url, **kwargs):
        assert method == "GET"
        response = requests.Response()
        response.status_code = 200
        payload = {"comments": [], "total": 0} if url.endswith("/comment") else {"isLast": True, "issues": rows}
        response._content = json.dumps(payload).encode()
        response.url = url
        return response

    monkeypatch.setattr("requests.Session.request", transport)
    imports = root + f"research/connections/{connection.data['id']}/imports/"
    job = session_client.post(imports, {"acknowledge_unsupported": True}, format="json")
    assert job.status_code == 202
    run_research_job.apply(args=[job.data["id"]], throw=True)
    status = session_client.get(imports).data[0]
    assert status["status"] == "completed", status["error"]
    issues = {issue.name: issue for issue in Issue.objects.filter(project=research_project)}

    def relations(name):
        response = session_client.get(root + f"issues/{issues[name].id}/issue-relation/")
        assert response.status_code == 200
        return {kind: {str(row["id"]) for row in values} for kind, values in response.data.items()}

    first, second, third = relations("Research 1"), relations("Research 2"), relations("Research 3")
    assert first["blocking"] == {str(issues["Research 2"].id)}
    assert first["blocked_by"] == set()
    assert second["blocked_by"] == {str(issues["Research 1"].id)}
    assert second["blocking"] == set()
    assert first["duplicate"] == {str(issues["Research 3"].id)}
    assert third["duplicate"] == {str(issues["Research 1"].id)}
