# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Explicit operator linking; login never links accounts by email."""
import hashlib

import requests
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from plane.db.models import Account, Project, ProjectMember, User, Workspace, WorkspaceMember
from plane.license.models import Instance, InstanceAdmin

from plane_sso.directory import directory_token, require_member


class Command(BaseCommand):
    help = "Link one existing Plane administrator to a live verified Auth0 company member"

    def add_arguments(self, parser):
        parser.add_argument("email")

    def handle(self, *args, **options):
        email = options["email"].strip().lower()
        if len(settings.AUTH0_ORGANIZATION_WORKSPACES) != 1:
            raise CommandError("Select exactly one company in the server configuration")
        organization, slug = next(iter(settings.AUTH0_ORGANIZATION_WORKSPACES.items()))
        base = settings.AUTH0_MANAGEMENT_URL.rstrip("/") + "/"
        identity = (base, email, organization, settings.AUTH0_DIRECTORY_CLIENT_ID)
        token = directory_token(base, identity)
        response = requests.get(base + "api/v2/users-by-email", params={"email": email},
            headers={"Authorization": "Bearer " + token}, timeout=5, allow_redirects=False)
        if response.status_code != 200:
            raise CommandError("Auth0 identity lookup failed")
        candidates = []
        for user in response.json():
            if user.get("email", "").lower() != email or user.get("email_verified") is not True or user.get("blocked"):
                continue
            try:
                require_member(user["user_id"], organization, fresh=True)
            except PermissionDenied:
                continue
            candidates.append(user["user_id"])
        if len(candidates) != 1:
            raise CommandError("Exactly one verified Auth0 company identity is required")
        subject = candidates[0]
        with transaction.atomic():
            for kind, value in (("subject", subject), ("email", email)):
                lock = int.from_bytes(hashlib.sha256((kind + value).encode()).digest()[:8], signed=True)
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_advisory_xact_lock(%s)", [lock])
            user = User.objects.select_for_update().get(email__iexact=email, is_active=True, is_bot=False)
            account = Account.objects.select_for_update().filter(provider="auth0", provider_account_id=subject).first()
            if account and (account.user_id != user.pk or account.metadata.get("issuer") != settings.AUTH0_ISSUER):
                raise CommandError("Existing identity binding conflicts")
            if Account.objects.filter(user=user, provider="auth0").exclude(provider_account_id=subject).exists():
                raise CommandError("Existing user has a different Auth0 identity")
            Account.objects.get_or_create(user=user, provider="auth0", provider_account_id=subject,
                defaults={"access_token": "", "refresh_token": "", "metadata": {"issuer": settings.AUTH0_ISSUER}})
            if user.has_usable_password():
                user.set_unusable_password()
            user.is_email_verified = True
            user.save(update_fields=["password", "is_email_verified"])
            workspace = Workspace.objects.get(slug=slug)
            WorkspaceMember.objects.update_or_create(workspace=workspace, member=user,
                                                     defaults={"role": 20, "is_active": True})
            for project in Project.objects.filter(workspace=workspace):
                ProjectMember.objects.update_or_create(workspace=workspace, project=project, member=user,
                                                       defaults={"role": 20, "is_active": True})
            InstanceAdmin.objects.update_or_create(instance=Instance.objects.get(), user=user,
                                                  defaults={"role": 20, "is_verified": True})
        self.stdout.write("Verified Auth0 identity linked; workspace, project, and instance administrator access confirmed")
