# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.db import models
from .project import ProjectBaseModel


class ResearchConnection(ProjectBaseModel):
    """A project-scoped provider installation. Credentials never enter serializers."""

    provider = models.CharField(max_length=16, choices=[(p, p) for p in ("github", "jira", "slack")])
    actor = models.ForeignKey("db.User", on_delete=models.CASCADE)
    config = models.JSONField(default=dict)
    encrypted_credentials = models.TextField()
    active = models.BooleanField(default=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["project", "provider"], name="research_project_provider")]


class ResearchJob(ProjectBaseModel):
    connection = models.ForeignKey(ResearchConnection, on_delete=models.CASCADE, related_name="jobs")
    status = models.CharField(max_length=16, default="queued")
    operation = models.CharField(max_length=16, default="import")
    cursor = models.JSONField(default=dict)
    processed = models.PositiveIntegerField(default=0)
    error = models.CharField(max_length=255, blank=True)
    delivery_id = models.CharField(max_length=255, null=True)
    payload = models.JSONField(default=dict)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["connection", "delivery_id"], name="research_delivery_once")]


class ResearchObject(ProjectBaseModel):
    """Durable source identity and outbound receipt, shared by retries and webhooks."""

    connection = models.ForeignKey(ResearchConnection, on_delete=models.CASCADE, related_name="source_objects")
    kind = models.CharField(max_length=32)
    source_id = models.CharField(max_length=255)
    issue = models.ForeignKey("db.Issue", on_delete=models.CASCADE)
    comment = models.ForeignKey("db.IssueComment", on_delete=models.SET_NULL, null=True)
    metadata = models.JSONField(default=dict)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["connection", "kind", "source_id"], name="research_source_once")]
