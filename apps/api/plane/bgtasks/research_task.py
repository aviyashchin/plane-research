# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from decimal import Decimal, InvalidOperation
from html import escape

from celery import shared_task
from django.db import connection as database, transaction
from plane.db.models import (
    Estimate,
    EstimatePoint,
    Issue,
    IssueAssignee,
    IssueComment,
    IssueLabel,
    IssueLink,
    IssueRelation,
    Label,
    ProjectMember,
    ResearchConnection,
    ResearchJob,
    ResearchObject,
    State,
    WorkspaceMember,
)
from plane.utils.research_providers import Provider


def actor_has_access(connection):
    return (
        WorkspaceMember.objects.filter(workspace=connection.workspace, member=connection.actor, is_active=True).exists()
        and ProjectMember.objects.filter(
            project=connection.project, member=connection.actor, is_active=True, role__in=[15, 20]
        ).exists()
    )


def plain_html(text):
    return "<p>" + escape(str(text or "")).replace("\n", "<br/>") + "</p>"


def issue_marker(connection, issue_id, kind="issue"):
    import hashlib
    import hmac
    from django.conf import settings

    signature = hmac.new(
        settings.SECRET_KEY.encode(), f"{kind}:{connection.id}:{issue_id}".encode(), hashlib.sha256
    ).hexdigest()
    return f"<!-- plane-{kind}:{issue_id}:{signature} -->"


def import_item(connection, item, comments):
    """Commit one issue and all its source identities together, before advancing the job."""
    project = connection.project
    source = f"research:{connection.id}"
    mapped = ResearchObject.objects.filter(connection=connection, kind="issue", source_id=item["id"]).first()
    issue = mapped.issue if mapped else None
    description = item["description"]
    if connection.provider == "github" and connection.config.get("sync"):
        import re

        match = re.search(r"<!-- plane-issue:([0-9a-f-]{36}):[0-9a-f]{64} -->", description)
        if match and match.group(0) == issue_marker(connection, match.group(1)):
            if not issue:
                issue = Issue.objects.filter(project=project, id=match.group(1), external_source__isnull=True).first()
            description = description.replace(match.group(0), "").strip()
    if issue is None:
        issue = Issue(project=project, external_source=source, external_id=item["id"])
    state_id = connection.config.get("state_map", {}).get(item["state_id"])
    if state_id:
        state = State.objects.get(id=state_id, project=project)
    else:
        state, _ = State.objects.get_or_create(
            project=project, name=item["state_name"], defaults={"group": item["group"], "color": "#60646C"}
        )
    if issue._state.adding or not connection.config.get("sync"):
        issue.state = state
    # An export acknowledgment must not replace a native rich document with source plain text.
    if issue._state.adding or issue.external_source is not None:
        issue.name = item["title"][:255]
        issue.description_html = plain_html(description)
    if connection.provider == "jira" or issue._state.adding:
        issue.priority = item["priority"]
        issue.target_date = item["due_date"]
    if item["estimate"] is not None:
        try:
            points = Decimal(str(item["estimate"]))
            if not points.is_finite() or points < 0:
                raise ValueError("Invalid source estimate")
        except InvalidOperation:
            raise ValueError("Invalid source estimate")
        estimate = project.estimate
        if not estimate:
            estimate, _ = Estimate.objects.get_or_create(
                project=project, name="Imported points", defaults={"type": "points"}
            )
            project.estimate = estimate
            project.save(update_fields=["estimate"])
        if estimate.type != "points":
            raise ValueError("Choose a numeric project estimate before importing points")
        point = EstimatePoint.objects.filter(estimate=estimate, value=str(points)).first()
        if not point:
            from django.db.models import Max

            key = EstimatePoint.objects.filter(estimate=estimate).aggregate(value=Max("key"))["value"]
            point = EstimatePoint.objects.create(
                project=project, estimate=estimate, key=(key or 0) + 1, value=str(points)
            )
        issue.estimate_point = point
    issue.save()
    if not mapped:
        mapped = ResearchObject.objects.create(
            connection=connection, project=project, kind="issue", source_id=item["id"], issue=issue
        )
    mapped.metadata = {
        "key": item["key"],
        "number": item["number"],
        "parent": item["parent"],
        "relations": item["relations"],
    }
    mapped.save(update_fields=["metadata", "updated_at"])
    for name in item["labels"]:
        label, _ = Label.objects.get_or_create(project=project, workspace=project.workspace, name=name[:255])
        IssueLabel.objects.get_or_create(project=project, issue=issue, label=label)
    # Existing local labels remain intact. Assignees use explicit, project-scoped mappings only.
    for source_user in item["assignees"]:
        member_id = connection.config.get("assignees", {}).get(source_user)
        if member_id and ProjectMember.objects.filter(project=project, member_id=member_id, is_active=True).exists():
            IssueAssignee.objects.get_or_create(project=project, issue=issue, assignee_id=member_id)
    IssueLink.objects.get_or_create(
        project=project, issue=issue, url=item["url"], defaults={"title": "Original source"}
    )
    for attachment in item["attachments"]:
        IssueLink.objects.get_or_create(
            project=project, issue=issue, url=attachment["url"], defaults={"title": attachment["name"][:255]}
        )
    outbound = list(ResearchObject.objects.filter(connection=connection, issue=issue, kind="outbound_comment"))
    remote_ids = {str(receipt.metadata.get("remote_id")) for receipt in outbound}
    source_comment_ids = {row["id"] for row in comments}
    deleted = ResearchObject.objects.filter(connection=connection, issue=issue, kind="comment").exclude(
        source_id__in=source_comment_ids
    )
    IssueComment.objects.filter(id__in=deleted.values("comment_id")).delete()
    deleted.delete()
    for row in comments:
        import re

        match = re.search(r"<!-- plane-comment:([0-9a-f-]{36}):[0-9a-f]{64} -->", row["text"])
        own_marker = match and match.group(0) == issue_marker(connection, match.group(1), "comment")
        if row["id"] in remote_ids or own_marker:
            # An outbound comment read back from GitHub must not become another local comment.
            continue
        record = ResearchObject.objects.filter(connection=connection, kind="comment", source_id=row["id"]).first()
        comment = (
            record.comment
            if record and record.comment
            else IssueComment(
                project=project,
                issue=issue,
                actor=connection.actor,
                external_source=source,
                external_id=row["id"],
                access="EXTERNAL",
            )
        )
        comment.comment_html = plain_html(row["author"] + ":\n" + row["text"])
        comment.save()
        if not record:
            ResearchObject.objects.create(
                connection=connection,
                project=project,
                kind="comment",
                source_id=row["id"],
                issue=issue,
                comment=comment,
            )
        elif record.comment_id != comment.id:
            record.comment = comment
            record.save(update_fields=["comment", "updated_at"])
    return issue, bool(mapped), item["group"]


def restore_relationships(connection):
    records = list(ResearchObject.objects.filter(connection=connection, kind="issue").select_related("issue"))
    keys = {record.metadata["key"]: record.issue for record in records}
    for record in records:
        parent = keys.get(record.metadata.get("parent"))
        if parent and parent.id != record.issue_id:
            # Reject cycles, including cycles that pass through previously imported parents.
            ancestor = parent
            seen = {record.issue_id}
            while ancestor:
                if ancestor.id in seen:
                    raise ValueError("Source parent relationship contains a cycle")
                seen.add(ancestor.id)
                ancestor = ancestor.parent
            record.issue.parent = parent
            record.issue.save(update_fields=["parent"])
        for relation in record.metadata.get("relations", []):
            related = keys.get(relation["key"])
            if related and related.id != record.issue_id:
                inverse = {
                    "blocking": "blocked_by",
                    "blocked_by": "blocking",
                    "duplicate": "duplicate",
                    "relates_to": "relates_to",
                }
                for source, target, kind in (
                    (record.issue, related, relation["type"]),
                    (related, record.issue, inverse[relation["type"]]),
                ):
                    IssueRelation.objects.get_or_create(
                        project=connection.project, issue=source, related_issue=target, defaults={"relation_type": kind}
                    )


def sync_github_issue(provider, item, issue, comments):
    """GitHub owns imported content; Plane owns state after the first import."""
    from plane.utils.html_processor import strip_tags

    connection = provider.connection
    state = "closed" if issue.state.group in ("completed", "cancelled") else "open"
    if (item["group"] in ("completed", "cancelled")) != (state == "closed") or (
        state == "closed" and item["group"] != issue.state.group
    ):
        provider.request(
            "PATCH",
            f"/repos/{connection.config['repository']}/issues/{item['number']}",
            json={
                "state": state,
                "state_reason": "not_planned"
                if issue.state.group == "cancelled"
                else "completed"
                if state == "closed"
                else "reopened",
            },
        )
    # Internal comments stay in Plane. Only EXTERNAL comments explicitly belong to the sync.
    for receipt in ResearchObject.objects.filter(
        connection=connection, issue=issue, kind="outbound_comment"
    ).select_related("comment"):
        if receipt.comment is None or receipt.comment.deleted_at is not None or receipt.comment.access != "EXTERNAL":
            provider.request(
                "DELETE", f"/repos/{connection.config['repository']}/issues/comments/{receipt.metadata['remote_id']}"
            )
            receipt.delete()
    for comment in IssueComment.objects.filter(issue=issue, external_source__isnull=True, access="EXTERNAL"):
        marker = issue_marker(connection, comment.id, "comment")
        body = strip_tags(comment.comment_html) + "\n\n" + marker
        receipt = ResearchObject.objects.filter(
            connection=connection, kind="outbound_comment", source_id=str(comment.id)
        ).first()
        remote = next(
            (
                row
                for row in comments
                if marker in row["text"] or (receipt and row["id"] == receipt.metadata.get("remote_id"))
            ),
            None,
        )
        if not remote:
            remote = provider.request(
                "POST",
                f"/repos/{connection.config['repository']}/issues/{item['number']}/comments",
                json={"body": body},
            )
        elif remote["text"] != body:
            provider.request(
                "PATCH", f"/repos/{connection.config['repository']}/issues/comments/{remote['id']}", json={"body": body}
            )
        ResearchObject.objects.get_or_create(
            connection=connection,
            project=connection.project,
            kind="outbound_comment",
            source_id=str(comment.id),
            defaults={"issue": issue, "comment": comment, "metadata": {"remote_id": str(remote["id"])}},
        )


def export_local_github_issues(provider):
    from plane.utils.html_processor import strip_tags

    connection = provider.connection
    mapped_ids = ResearchObject.objects.filter(connection=connection, kind="issue").values_list("issue_id", flat=True)
    for issue in Issue.issue_objects.filter(project=connection.project, external_source__isnull=True).exclude(
        id__in=mapped_ids
    ):
        row = provider.request(
            "POST",
            f"/repos/{connection.config['repository']}/issues",
            json={
                "title": issue.name,
                "body": strip_tags(issue.description_html) + "\n\n" + issue_marker(connection, issue.id),
            },
        )
        item = provider.github_issue(row)
        with transaction.atomic():
            imported, _, _ = import_item(connection, item, [])
        sync_github_issue(provider, item, imported, [])


def create_slack_issue(job):
    connection = job.connection
    with transaction.atomic():
        existing = ResearchObject.objects.filter(
            connection=connection, kind="slack_command", source_id=job.delivery_id
        ).first()
        if not existing:
            text = job.payload["text"]
            issue = Issue.objects.create(
                project=connection.project, name=text.split("\n")[0][:255], description_html=plain_html(text)
            )
            ResearchObject.objects.create(
                connection=connection,
                project=connection.project,
                kind="slack_command",
                source_id=job.delivery_id,
                issue=issue,
            )
        job.status, job.processed = "completed", 1
        job.save(update_fields=["status", "processed", "updated_at"])


def notify_slack(job):
    import uuid

    connection = job.connection
    issue = (
        Issue.issue_objects.filter(id=job.payload["issue_id"], project=connection.project)
        .select_related("state")
        .first()
    )
    if issue:
        provider = Provider(connection)
        text = f"{escape(issue.name)} — {escape(issue.state.name)}"
        record = ResearchObject.objects.filter(
            connection=connection, kind="slack_message", source_id=str(issue.id)
        ).first()
        data = {
            "channel": connection.config["channel_id"],
            "text": text,
            "parse": "none",
            "unfurl_links": False,
            "unfurl_media": False,
        }
        if record:
            data["ts"] = record.metadata["ts"]
            provider.request("POST", "/chat.update", json=data)
        else:
            data["client_msg_id"] = str(uuid.uuid5(connection.id, str(issue.id)))
            result = provider.request("POST", "/chat.postMessage", json=data)
            ResearchObject.objects.create(
                connection=connection,
                project=connection.project,
                kind="slack_message",
                source_id=str(issue.id),
                issue=issue,
                metadata={"ts": result["ts"]},
            )
    job.status, job.processed = "completed", 1
    job.save(update_fields=["status", "processed", "updated_at"])


def queue_research_activity(project_id, issue_id, activity_type, epoch):
    if activity_type not in (
        "issue.activity.created",
        "issue.activity.updated",
        "comment.activity.created",
        "comment.activity.updated",
        "comment.activity.deleted",
    ):
        return
    for installation in ResearchConnection.objects.filter(project_id=project_id, active=True):
        notify = (
            installation.provider == "slack"
            and installation.config.get("notify")
            and activity_type.startswith("issue.")
        )
        sync = installation.provider == "github" and installation.config.get("sync")
        if notify or sync:
            job, created = ResearchJob.objects.get_or_create(
                connection=installation,
                delivery_id=f"activity:{issue_id}:{activity_type}:{epoch}",
                defaults={
                    "project_id": project_id,
                    "operation": "notify" if notify else "sync",
                    "payload": {"issue_id": str(issue_id)},
                },
            )
            if created:
                transaction.on_commit(lambda job_id=str(job.id): run_research_job.delay(job_id))


@shared_task(bind=True, acks_late=True, reject_on_worker_lost=True, max_retries=None)
def run_research_job(self, job_id):
    job = ResearchJob.objects.select_related("connection__project", "connection__actor").filter(id=job_id).first()
    if not job or job.status == "completed":
        return
    lock_key = job.connection_id.int % (2**63 - 1)
    with database.cursor() as cursor:
        cursor.execute("SELECT pg_try_advisory_lock(%s)", [lock_key])
        locked = cursor.fetchone()[0]
    if not locked:
        raise self.retry(countdown=10)
    try:
        job.refresh_from_db()
        if job.status == "completed":
            return
        connection = job.connection
        if not connection.active or not actor_has_access(connection):
            raise ValueError("Installation disconnected or actor no longer has access")
        job.status, job.error = "processing", ""
        job.save(update_fields=["status", "error", "updated_at"])
        if job.operation == "slack_create":
            create_slack_issue(job)
            return
        if job.operation == "notify":
            notify_slack(job)
            return
        provider = Provider(connection)
        while True:
            connection.refresh_from_db()
            if not connection.active or not actor_has_access(connection):
                raise ValueError("Installation disconnected or actor no longer has access")
            page = job.cursor.get("page", {})
            items, next_page = provider.issue_page(page)
            offset = job.cursor.get("offset", 0)
            for index, item in enumerate(items[offset:], start=offset):
                comments = list(provider.comments(item))
                with transaction.atomic():
                    issue, _, _ = import_item(connection, item, comments)
                if connection.provider == "github" and connection.config.get("sync"):
                    sync_github_issue(provider, item, issue, comments)
                with transaction.atomic():
                    job.processed += 1
                    job.cursor = {"page": page, "offset": index + 1}
                    job.save(update_fields=["cursor", "processed", "updated_at"])
            if next_page is None:
                break
            job.cursor = {"page": next_page, "offset": 0}
            job.save(update_fields=["cursor", "updated_at"])
        with transaction.atomic():
            restore_relationships(connection)
        if connection.provider == "github" and connection.config.get("sync"):
            export_local_github_issues(provider)
        with transaction.atomic():
            job.status = "completed"
            job.save(update_fields=["status", "updated_at"])
    except Exception as error:
        # Provider exceptions can contain credentials, response bodies, or signed attachment URLs.
        job.status = "failed"
        job.error = (
            f"{type(error).__name__}: import stopped; "
            "verify provider access, mappings and project estimates, then retry"
        )
        job.save(update_fields=["status", "error", "updated_at"])
        from requests.exceptions import RequestException

        if isinstance(error, RequestException) and self.request.retries < 3:
            raise self.retry(countdown=30 * (2**self.request.retries))
    finally:
        with database.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_unlock(%s)", [lock_key])
