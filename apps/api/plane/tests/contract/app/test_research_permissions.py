# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import hashlib
import hmac
import time

import pytest
from cryptography.fernet import Fernet
from rest_framework.test import APIClient

from plane.db.models import (
    Issue,
    Page,
    Project,
    ProjectMember,
    ProjectPage,
    ResearchConnection,
    ResearchJob,
    State,
    User,
    Workspace,
    WorkspaceMember,
)


pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture
def permission_project(workspace, create_user, monkeypatch, settings):
    settings.WEB_URL = "http://localhost:3000"
    monkeypatch.setenv("RESEARCH_CREDENTIAL_KEY", Fernet.generate_key().decode())
    project = Project.objects.create(name="Restricted research", identifier="SEC", workspace=workspace)
    ProjectMember.objects.create(project=project, member=create_user, role=20)
    return project


@pytest.fixture
def foreign_project():
    outsider = User.objects.create(email="outsider@example.com", username="outsider", first_name="Outsider")
    workspace = Workspace.objects.create(name="Foreign workspace", slug="foreign-research", owner=outsider)
    WorkspaceMember.objects.create(workspace=workspace, member=outsider, role=20)
    project = Project.objects.create(name="Foreign research", identifier="FOR", workspace=workspace)
    ProjectMember.objects.create(project=project, member=outsider, role=20)
    return project


@pytest.fixture
def github_installation(session_client, workspace, permission_project):
    root = f"/api/workspaces/{workspace.slug}/projects/{permission_project.id}/research/"
    response = session_client.post(
        root + "connections/",
        {
            "provider": "github",
            "config": {"repository": "owner/research"},
            "credentials": {"token": "private-test-token", "webhook_secret": "private-test-hook"},
        },
        format="json",
    )
    assert response.status_code == 201
    return root, response.data


@pytest.mark.parametrize("identity", ["foreign-user", "foreign-workspace"])
@pytest.mark.parametrize(
    "method, endpoint",
    [
        ("get", "connections/"),
        ("post", "connections/"),
        ("delete", "connections/{connection_id}/"),
        ("get", "connections/{connection_id}/imports/"),
        ("post", "connections/{connection_id}/imports/"),
        ("post", "jobs/{job_id}/retry/"),
        ("get", "summary/"),
    ],
)
def test_known_identifiers_do_not_grant_foreign_access(
    session_client, workspace, permission_project, foreign_project, github_installation, identity, method, endpoint
):
    root, installation = github_installation
    connection = ResearchConnection.objects.get(id=installation["id"])
    job = ResearchJob.objects.create(project=permission_project, connection=connection)
    client = session_client
    if identity == "foreign-user":
        client = APIClient()
        client.force_authenticate(user=foreign_project.workspace.owner)
    else:
        root = root.replace(f"/{workspace.slug}/", f"/{foreign_project.workspace.slug}/")
    url = root + endpoint.format(connection_id=installation["id"], job_id=job.id)
    request = getattr(client, method)
    response = request(url, {"action": "preview"}, format="json") if method == "post" else request(url)
    assert response.status_code in (403, 404)
    connection.refresh_from_db()
    job.refresh_from_db()
    assert connection.active
    assert job.status == "queued"
    assert ResearchConnection.objects.filter(project=permission_project).count() == 1


@pytest.mark.parametrize("mapping", ["foreign-state", "foreign-assignee", "inactive-assignee"])
def test_mapping_rejects_foreign_project_and_inactive_members(
    session_client, workspace, permission_project, foreign_project, create_user, mapping
):
    config = {"repository": "owner/research"}
    if mapping == "foreign-state":
        state = State.objects.create(project=foreign_project, name="Foreign done", group="completed", color="#000000")
        config["state_map"] = {"closed": str(state.id)}
    elif mapping == "foreign-assignee":
        config["assignees"] = {"source-user": str(foreign_project.workspace.owner_id)}
    else:
        inactive = User.objects.create(email="inactive@example.com", username="inactive", first_name="Inactive")
        WorkspaceMember.objects.create(workspace=workspace, member=inactive, role=15)
        ProjectMember.objects.create(project=permission_project, member=inactive, role=15, is_active=False)
        config["assignees"] = {"source-user": str(inactive.id)}
    response = session_client.post(
        f"/api/workspaces/{workspace.slug}/projects/{permission_project.id}/research/connections/",
        {"provider": "github", "config": config, "credentials": {"token": "private-test-token"}},
        format="json",
    )
    assert response.status_code == 400
    assert not ResearchConnection.objects.filter(project=permission_project).exists()


@pytest.mark.parametrize("source", ["private-page", "foreign-project", "foreign-workspace"])
def test_assistant_cannot_read_private_or_foreign_page(
    session_client, workspace, permission_project, foreign_project, create_user, monkeypatch, source
):
    monkeypatch.setenv("LLM_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.setenv("LLM_MODEL", "research-local")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    page_workspace, page_project, owner, access = workspace, permission_project, foreign_project.workspace.owner, 1
    if source == "foreign-project":
        page_project = Project.objects.create(name="Other project", identifier="OTH", workspace=workspace)
        owner, access = create_user, 0
    elif source == "foreign-workspace":
        page_workspace, page_project, access = foreign_project.workspace, foreign_project, 0
    page = Page.objects.create(
        workspace=page_workspace,
        name="Restricted notes",
        owned_by=owner,
        access=access,
        description_html="<p>Do not send these confidential notes to a model.</p>",
    )
    ProjectPage.objects.create(workspace=page_workspace, project=page_project, page=page)

    def reject_inference(*args, **kwargs):
        pytest.fail("An inaccessible page must be rejected before contacting an inference provider")

    monkeypatch.setattr("httpx.Client.send", reject_inference)
    response = session_client.post(
        f"/api/workspaces/{workspace.slug}/projects/{permission_project.id}/ai-assistant/",
        {"task": "Draft an issue", "page_id": str(page.id)},
        format="json",
    )
    assert response.status_code == 404


@pytest.mark.parametrize("body", [b"{invalid", b"[]"])
def test_signed_malformed_github_payload_returns_bad_request(github_installation, body):
    _, installation = github_installation
    signature = "sha256=" + hmac.new(b"private-test-hook", body, hashlib.sha256).hexdigest()
    response = APIClient().post(
        f"/api/research/hooks/{installation['id']}/github/",
        body,
        content_type="application/json",
        HTTP_X_HUB_SIGNATURE_256=signature,
        HTTP_X_GITHUB_DELIVERY="malformed-delivery",
        HTTP_X_GITHUB_EVENT="issues",
    )
    assert response.status_code == 400
    assert not ResearchJob.objects.filter(connection_id=installation["id"]).exists()


def test_stale_slack_signature_cannot_create_a_job(session_client, workspace, permission_project):
    response = session_client.post(
        f"/api/workspaces/{workspace.slug}/projects/{permission_project.id}/research/connections/",
        {
            "provider": "slack",
            "config": {"team_id": "T123", "channel_id": "C123", "notify": False},
            "credentials": {"token": "private-slack-token", "signing_secret": "private-slack-secret"},
        },
        format="json",
    )
    assert response.status_code == 201
    installation = response.data
    timestamp = str(int(time.time()) - 3600)
    body = b"team_id=T123&channel_id=C123&text=Stale+research+command"
    signature = (
        "v0=" + hmac.new(b"private-slack-secret", b"v0:" + timestamp.encode() + b":" + body, hashlib.sha256).hexdigest()
    )
    response = APIClient().post(
        f"/api/research/hooks/{installation['id']}/slack/",
        body,
        content_type="application/x-www-form-urlencoded",
        HTTP_X_SLACK_REQUEST_TIMESTAMP=timestamp,
        HTTP_X_SLACK_SIGNATURE=signature,
    )
    assert response.status_code == 403
    assert not ResearchJob.objects.filter(connection_id=installation["id"]).exists()


def test_disconnect_prevents_queued_import_and_erases_credentials(
    session_client, permission_project, github_installation, monkeypatch
):
    from plane.bgtasks.research_task import run_research_job

    root, installation = github_installation
    job = session_client.post(
        root + f"connections/{installation['id']}/imports/", {"acknowledge_unsupported": True}, format="json"
    )
    assert job.status_code == 202
    response = session_client.delete(root + f"connections/{installation['id']}/")
    assert response.status_code == 204

    def reject_provider(*args, **kwargs):
        pytest.fail("A disconnected installation must stop before contacting the provider")

    monkeypatch.setattr("requests.Session.request", reject_provider)
    run_research_job.apply(args=[job.data["id"]], throw=True)
    saved_job = ResearchJob.objects.get(id=job.data["id"])
    connection = ResearchConnection.objects.get(id=installation["id"])
    assert saved_job.status == "failed"
    assert saved_job.processed == 0
    assert not Issue.objects.filter(project=permission_project).exists()
    assert not connection.active
    assert connection.encrypted_credentials == ""
    assert session_client.post(root + f"jobs/{saved_job.id}/retry/", {}, format="json").status_code == 404


def test_provider_secrets_stay_encrypted_and_outside_api_responses(session_client, github_installation):
    root, installation = github_installation
    connection = ResearchConnection.objects.get(id=installation["id"])
    saved_values = str(connection.__dict__)
    for secret in ("private-test-token", "private-test-hook"):
        assert secret not in saved_values
        assert secret not in str(installation)
        assert secret not in str(session_client.get(root + "connections/").data)
    assert connection.encrypted_credentials
    assert "encrypted_credentials" not in installation
    assert "credentials" not in installation
