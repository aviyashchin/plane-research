# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import pytest
from plane.db.models import Project, ProjectMember


@pytest.mark.contract
@pytest.mark.django_db
def test_local_assistant_accepts_current_models_and_escapes_html(session_client, workspace, create_user, monkeypatch):
    project = Project.objects.create(name="Research", identifier="RES", workspace=workspace)
    ProjectMember.objects.create(project=project, member=create_user, role=20)
    monkeypatch.setenv("LLM_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.setenv("LLM_MODEL", "research-local")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    from unittest.mock import patch

    with patch("plane.app.views.external.base.OpenAI") as provider:
        provider.return_value.chat.completions.create.return_value.choices[
            0
        ].message.content = "<script>alert(1)</script>\nDraft"
        response = session_client.post(
            f"/api/workspaces/{workspace.slug}/projects/{project.id}/ai-assistant/",
            {"task": "Summarize", "prompt": "Research notes"},
            format="json",
        )
        assert response.status_code == 200
        assert response.data["response_html"] == "&lt;script&gt;alert(1)&lt;/script&gt;<br/>Draft"
        assert provider.call_args.kwargs["base_url"] == "http://localhost:11434/v1"
        assert provider.return_value.chat.completions.create.call_args.kwargs["model"] == "research-local"


@pytest.mark.contract
@pytest.mark.django_db
def test_page_to_issue_uses_accessible_page_text(session_client, workspace, create_user, monkeypatch):
    from plane.db.models import Page, ProjectPage
    from unittest.mock import patch

    project = Project.objects.create(name="Pages", identifier="PAG", workspace=workspace)
    ProjectMember.objects.create(project=project, member=create_user, role=20)
    page = Page.objects.create(
        workspace=workspace, name="Notes", owned_by=create_user, description_html="<p>Interview twelve buyers.</p>"
    )
    ProjectPage.objects.create(project=project, workspace=workspace, page=page)
    monkeypatch.setenv("LLM_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.setenv("LLM_MODEL", "research-local")
    with patch("plane.app.views.external.base.OpenAI") as provider:
        provider.return_value.chat.completions.create.return_value.choices[0].message.content = "Interview buyers"
        response = session_client.post(
            f"/api/workspaces/{workspace.slug}/projects/{project.id}/ai-assistant/",
            {"task": "Draft an issue", "page_id": str(page.id)},
            format="json",
        )
        assert response.status_code == 200
        assert (
            "Interview twelve buyers."
            in provider.return_value.chat.completions.create.call_args.kwargs["messages"][0]["content"]
        )


@pytest.mark.contract
@pytest.mark.django_db
def test_empty_model_response_and_invalid_input_do_not_create_content(
    session_client, workspace, create_user, monkeypatch
):
    from unittest.mock import patch
    from plane.db.models import Issue

    project = Project.objects.create(name="Empty model", identifier="EMP", workspace=workspace)
    ProjectMember.objects.create(project=project, member=create_user, role=20)
    monkeypatch.setenv("LLM_BASE_URL", "http://localhost:11434/v1")
    endpoint = f"/api/workspaces/{workspace.slug}/projects/{project.id}/ai-assistant/"
    with patch("plane.app.views.external.base.OpenAI") as provider:
        provider.return_value.chat.completions.create.return_value.choices[0].message.content = ""
        response = session_client.post(endpoint, {"task": "Draft", "prompt": "Notes"}, format="json")
        assert response.status_code == 500
        assert not Issue.objects.filter(project=project).exists()
        provider.reset_mock()
        for payload in ({"task": ["Draft"]}, {"task": "Draft", "prompt": {"secret": "value"}}):
            assert session_client.post(endpoint, payload, format="json").status_code == 400
        provider.assert_not_called()
