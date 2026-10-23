# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Real native API calls detect a return to the Pages-only pilot."""
from datetime import timedelta
from unittest.mock import patch

from django.conf import settings
from django.test import TestCase
from django.utils import timezone
from plane.db.models import Account, Profile, User, Workspace, WorkspaceMember
from plane.license.models import Instance, InstanceAdmin
from plane_sso.models import LoginGrant


class NativeCommunitySSO(TestCase):
    def setUp(self):
        self.directory = patch("plane_sso.access.require_member")
        self.directory.start()
        self.addCleanup(self.directory.stop)
        self.user = User.objects.create(username="admin", email="admin@example.com", is_email_verified=True)
        self.user.set_unusable_password()
        self.user.save()
        Profile.objects.get_or_create(user=self.user)
        self.workspace = Workspace.objects.create(name="Company", slug="company", owner=self.user)
        WorkspaceMember.objects.create(workspace=self.workspace, member=self.user, role=20)
        Account.objects.create(user=self.user, provider="auth0", provider_account_id="auth0|admin",
                               metadata={"issuer": settings.AUTH0_ISSUER})
        self.instance = Instance.objects.create(instance_name="Test", instance_id="test",
            current_version="v1.4.2", last_checked_at=timezone.now(), is_setup_done=True)
        InstanceAdmin.objects.create(instance=self.instance, user=self.user, role=20, is_verified=True)
        self.client.force_login(self.user)
        self.grant = LoginGrant.objects.create(organization="org_company", consumed=True,
                                              expires_at=timezone.now() + timedelta(hours=1))
        session = self.client.session
        session["auth0"] = {"issuer": settings.AUTH0_ISSUER, "sub": "auth0|admin",
            "organization": "org_company", "workspace": str(self.workspace.pk),
            "deadline": (timezone.now() + timedelta(hours=1)).timestamp(), "grant": str(self.grant.pk)}
        session.save()

    def test_administrator_can_create_native_project_and_work_item(self):
        response = self.client.post("/api/workspaces/company/projects/", {
            "name": "Full Community", "identifier": "FULL"}, content_type="application/json",
            HTTP_ORIGIN=settings.AUTH0_BASE_URL)
        self.assertEqual(response.status_code, 201, response.content)
        project = response.json()["id"]
        response = self.client.post(f"/api/workspaces/company/projects/{project}/issues/", {
            "name": "Native SSO work item", "description_html": "<p>Persisted through native API</p>"},
            content_type="application/json", HTTP_ORIGIN=settings.AUTH0_BASE_URL)
        self.assertEqual(response.status_code, 201, response.content)
        item = response.json()["id"]
        response = self.client.get(f"/api/workspaces/company/projects/{project}/issues/{item}/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["name"], "Native SSO work item")

    def test_sso_administrator_can_use_god_mode_with_same_session(self):
        response = self.client.get("/api/instances/admins/me/")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["email"], self.user.email)

    def test_password_session_without_sso_cannot_read_company_data(self):
        session = self.client.session
        session.pop("auth0")
        session.save()
        self.assertEqual(self.client.get("/api/users/me/").status_code, 401)

    def test_revoked_login_cannot_read_company_data(self):
        self.grant.revoked = True
        self.grant.save()
        self.assertEqual(self.client.get("/api/users/me/").status_code, 401)

    def test_other_origin_cannot_change_company_data(self):
        response = self.client.post("/api/workspaces/company/projects/", {
            "name": "Forbidden", "identifier": "NO"}, content_type="application/json",
            HTTP_ORIGIN="https://attacker.example")
        self.assertEqual(response.status_code, 403)

    def test_native_password_login_stays_disabled(self):
        self.client.logout()
        response = self.client.post("/auth/sign-in/", {"email": self.user.email, "password": "irrelevant"})
        self.assertEqual(response.status_code, 403)

    def test_company_members_do_not_inherit_instance_administrator(self):
        InstanceAdmin.objects.filter(user=self.user).delete()
        self.assertEqual(self.client.get("/api/instances/admins/me/").status_code, 403)

    def test_native_browser_entry_requires_sso(self):
        self.assertEqual(self.client.get("/auth/auth0/check/").status_code, 204)
        self.client.logout()
        response = self.client.get("/auth/auth0/check/", HTTP_X_FORWARDED_URI="/god-mode/general/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/auth/auth0/?next=%2Fgod-mode%2Fgeneral%2F")

    def test_native_work_item_destination_survives_sso_entry(self):
        target = "/company/projects/123/issues/456/?view=board"
        response = self.client.get("/auth/auth0/", {"next_path": target})
        self.assertEqual(response["Location"], target)

    def test_external_destination_is_ignored(self):
        response = self.client.get("/auth/auth0/", {"next": "//attacker.example/company/"})
        self.assertEqual(response["Location"], "/company/")

    def test_non_administrator_browser_cannot_loop_into_god_mode(self):
        InstanceAdmin.objects.filter(user=self.user).delete()
        response = self.client.get("/auth/auth0/check/", HTTP_X_FORWARDED_URI="/god-mode/general/")
        self.assertEqual(response.status_code, 403)
        self.assertContains(response, "Instance administrator access required", status_code=403)
