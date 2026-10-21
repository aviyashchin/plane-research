# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.shortcuts import get_object_or_404
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError

from plane.app.permissions import ROLE, allow_permission
from plane.app.views.base import BaseAPIView
from plane.db.models import Project, ResearchConnection
from plane.utils.research import connection_data, encrypt_credentials, validate_connection
from plane.utils.research import job_data
from plane.utils.research_providers import Provider, IMPORT_LIMITATIONS
from plane.db.models import ResearchJob, Issue, IssueComment, State, ProjectMember
from django.db import transaction


class ResearchConnectionsEndpoint(BaseAPIView):
    @allow_permission([ROLE.ADMIN])
    def get(self, request, slug, project_id):
        connections = ResearchConnection.objects.filter(workspace__slug=slug, project_id=project_id)
        return Response([connection_data(connection) for connection in connections])

    @allow_permission([ROLE.ADMIN])
    def post(self, request, slug, project_id):
        project = get_object_or_404(Project, id=project_id, workspace__slug=slug)
        provider = request.data.get("provider")
        config = validate_connection(provider, request.data.get("config", {}))
        credentials = request.data.get("credentials", {})
        if not isinstance(credentials, dict) or not credentials.get("token"):
            raise ValidationError("A provider token is required")
        if any(not isinstance(value, str) or len(value) > 10000 for value in credentials.values()):
            raise ValidationError("Credentials must contain text values of at most 10000 characters")
        if provider == "jira" and not credentials.get("email"):
            raise ValidationError("The Jira account email is required")
        for field, model, lookup in [("state_map", State, "id"), ("assignees", ProjectMember, "member_id")]:
            mapping = config.get(field, {})
            if not isinstance(mapping, dict):
                raise ValidationError("State and assignee mappings must be objects")
            for value in mapping.values():
                query = model.objects.filter(project=project, **{lookup: value})
                if model == ProjectMember:
                    query = query.filter(is_active=True)
                if not query.exists():
                    raise ValidationError("Mappings must belong to this project")
        source_fields = {"github": ("repository",), "jira": ("site", "project_key"), "slack": ("team_id", "channel_id")}
        with transaction.atomic():
            existing = ResearchConnection.objects.select_for_update().filter(project=project, provider=provider).first()
            if existing and any(existing.config.get(key) != config.get(key) for key in source_fields[provider]):
                raise ValidationError(
                    "This project's provider source is fixed. Use another project for a different source"
                )
            connection, _ = ResearchConnection.objects.update_or_create(
                project=project,
                provider=provider,
                defaults={
                    "actor": request.user,
                    "config": config,
                    "active": True,
                    "encrypted_credentials": encrypt_credentials(credentials),
                },
            )
        return Response(connection_data(connection), status=201)


class ResearchConnectionEndpoint(BaseAPIView):
    @allow_permission([ROLE.ADMIN])
    def delete(self, request, slug, project_id, connection_id):
        connection = get_object_or_404(
            ResearchConnection,
            id=connection_id,
            project_id=project_id,
            workspace__slug=slug,
        )
        connection.active = False
        connection.encrypted_credentials = ""
        connection.save(update_fields=["active", "encrypted_credentials", "updated_at"])
        return Response(status=204)


class ResearchImportsEndpoint(BaseAPIView):
    def installation(self, slug, project_id, connection_id):
        return get_object_or_404(
            ResearchConnection, id=connection_id, project_id=project_id, workspace__slug=slug, active=True
        )

    @allow_permission([ROLE.ADMIN])
    def get(self, request, slug, project_id, connection_id):
        connection = self.installation(slug, project_id, connection_id)
        return Response([job_data(job) for job in connection.jobs.order_by("-created_at")[:50]])

    @allow_permission([ROLE.ADMIN])
    def post(self, request, slug, project_id, connection_id):
        connection = self.installation(slug, project_id, connection_id)
        if connection.provider not in ("github", "jira"):
            raise ValidationError("Only GitHub and Jira provide issue imports")
        if request.data.get("action") == "preview":
            try:
                items, next_page = Provider(connection).issue_page({})
            except Exception:
                raise ValidationError("Cannot read the provider. Verify the token, scopes and source project")
            return Response(
                {
                    "sample": items[:20],
                    "has_more": bool(next_page) or len(items) > 20,
                    "limitations": IMPORT_LIMITATIONS,
                }
            )
        if request.data.get("acknowledge_unsupported") is not True:
            raise ValidationError("Preview and acknowledge import limitations before starting")
        from plane.bgtasks.research_task import run_research_job

        with transaction.atomic():
            ResearchConnection.objects.select_for_update().get(id=connection.id)
            job = connection.jobs.filter(status__in=["queued", "processing"]).first()
            if not job:
                job = ResearchJob.objects.create(project=connection.project, connection=connection)
            job_id = str(job.id)
            transaction.on_commit(lambda: run_research_job.delay(job_id))
        return Response(job_data(job), status=202)


class ResearchRetryEndpoint(BaseAPIView):
    @allow_permission([ROLE.ADMIN])
    def post(self, request, slug, project_id, job_id):
        job = get_object_or_404(
            ResearchJob, id=job_id, project_id=project_id, workspace__slug=slug, connection__active=True
        )
        if job.status not in ("failed", "queued", "processing"):
            raise ValidationError("Only unfinished jobs can resume")
        from plane.bgtasks.research_task import run_research_job

        run_research_job.delay(str(job.id))
        return Response(job_data(job), status=202)


class ResearchSummaryEndpoint(BaseAPIView):
    """Numeric estimate totals missing from the current count-based analytics cards."""

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER])
    def get(self, request, slug, project_id):
        from decimal import Decimal, InvalidOperation

        issues = Issue.issue_objects.filter(project_id=project_id, workspace__slug=slug)
        if request.GET.get("cycle_id"):
            issues = issues.filter(issue_cycle__cycle_id=request.GET["cycle_id"])
        if request.GET.get("module_id"):
            issues = issues.filter(issue_module__module_id=request.GET["module_id"])
        if request.GET.get("state_group"):
            issues = issues.filter(state__group=request.GET["state_group"])
        group_by = request.GET.get("group_by", "state__name")
        if group_by not in ("state__name", "priority"):
            raise ValidationError("Group by state__name or priority")
        groups = {}
        total, count = Decimal(0), 0
        for row in issues.values("id", group_by, "estimate_point__value").distinct():
            group = groups.setdefault(row[group_by] or "Unassigned", {"count": 0, "estimate_points": Decimal(0)})
            count += 1
            group["count"] += 1
            try:
                points = Decimal(row["estimate_point__value"] or "0")
                if points.is_finite():
                    total += points
                    group["estimate_points"] += points
            except InvalidOperation:
                pass
        if request.GET.get("format") == "csv":
            import csv
            from django.http import HttpResponse

            response = HttpResponse(content_type="text/csv")
            response["Content-Disposition"] = 'attachment; filename="research-analytics.csv"'
            writer = csv.writer(response)
            writer.writerow(["Group", "Issues", "Estimate points"])
            for name, values in groups.items():
                writer.writerow(
                    [
                        ("'" + name) if name.startswith(("=", "+", "-", "@")) else name,
                        values["count"],
                        values["estimate_points"],
                    ]
                )
            return response
        return Response(
            {
                "count": count,
                "estimate_points": total,
                "groups": groups,
                "comments": IssueComment.objects.filter(issue__in=issues).count(),
            }
        )


class ResearchHookEndpoint(BaseAPIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request, connection_id, provider):
        import hashlib
        import hmac
        import json
        import time
        from urllib.parse import parse_qs
        from plane.utils.research import decrypt_credentials

        connection = get_object_or_404(ResearchConnection, id=connection_id, provider=provider, active=True)
        credentials = decrypt_credentials(connection)
        body = request.body
        if len(body) > 2_000_000:
            return Response(status=413)
        if provider == "github":
            secret = credentials.get("webhook_secret")
            expected = "sha256=" + hmac.new((secret or "").encode(), body, hashlib.sha256).hexdigest()
            if not secret or not hmac.compare_digest(expected, request.headers.get("X-Hub-Signature-256", "")):
                return Response(status=403)
            try:
                payload = json.loads(body)
                if not isinstance(payload, dict):
                    raise ValueError()
            except (ValueError, UnicodeDecodeError):
                raise ValidationError("Webhook must contain a JSON object")
            if (payload.get("repository") or {}).get("full_name", "").lower() != connection.config[
                "repository"
            ].lower():
                return Response(status=403)
            delivery = request.headers.get("X-GitHub-Delivery", "")
            if request.headers.get("X-GitHub-Event") not in ("issues", "issue_comment"):
                return Response(status=204)
            operation, payload = "sync", {}
        elif provider == "slack":
            timestamp = request.headers.get("X-Slack-Request-Timestamp", "")
            try:
                if abs(time.time() - int(timestamp)) > 300:
                    return Response(status=403)
            except ValueError:
                return Response(status=403)
            secret = credentials.get("signing_secret")
            expected = (
                "v0="
                + hmac.new(
                    (secret or "").encode(), b"v0:" + timestamp.encode() + b":" + body, hashlib.sha256
                ).hexdigest()
            )
            if not secret or not hmac.compare_digest(expected, request.headers.get("X-Slack-Signature", "")):
                return Response(status=403)
            try:
                values = parse_qs(body.decode())
            except UnicodeDecodeError:
                raise ValidationError("Command must contain UTF-8 text")
            if any(values.get(key, [""])[0] != connection.config[key] for key in ("team_id", "channel_id")):
                return Response(status=403)
            text = values.get("text", [""])[0].strip()
            if not text or len(text) > 50000:
                raise ValidationError("Issue text must contain 1 to 50000 characters")
            delivery = "slack:" + hashlib.sha256(timestamp.encode() + body).hexdigest()
            operation, payload = "slack_create", {"text": text}
        else:
            return Response(status=404)
        if not delivery or len(delivery) > 255:
            raise ValidationError("A delivery ID is required")
        from plane.bgtasks.research_task import run_research_job

        with transaction.atomic():
            job, created = ResearchJob.objects.get_or_create(
                connection=connection,
                delivery_id=delivery,
                defaults={"project": connection.project, "operation": operation, "payload": payload},
            )
            if created:
                transaction.on_commit(lambda: run_research_job.delay(str(job.id)))
        return Response({"response_type": "ephemeral", "text": "Plane accepted this request."})
