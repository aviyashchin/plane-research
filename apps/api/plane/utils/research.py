# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import json
import os
import re

from cryptography.fernet import Fernet
from rest_framework.exceptions import ValidationError


def credential_cipher():
    key = os.environ.get("RESEARCH_CREDENTIAL_KEY", "")
    if not key:
        raise ValidationError("The operator must set RESEARCH_CREDENTIAL_KEY before connecting providers")
    try:
        return Fernet(key.encode())
    except ValueError:
        raise ValidationError("RESEARCH_CREDENTIAL_KEY must be a Fernet key")


def encrypt_credentials(credentials):
    if not isinstance(credentials, dict):
        raise ValidationError("Credentials must be an object")
    return credential_cipher().encrypt(json.dumps(credentials).encode()).decode()


def decrypt_credentials(connection):
    return json.loads(credential_cipher().decrypt(connection.encrypted_credentials.encode()))


def validate_connection(provider, config):
    if not isinstance(config, dict):
        raise ValidationError("Configuration must be an object")
    allowed = {
        "github": {"repository", "sync", "assignees", "state_map"},
        "jira": {"site", "project_key", "assignees", "state_map", "priority_map", "estimate_field"},
        "slack": {"team_id", "channel_id", "notify"},
    }
    if not isinstance(provider, str) or provider not in allowed or set(config) - allowed[provider]:
        raise ValidationError("Unsupported provider or configuration fields")
    for field in ("sync", "notify"):
        if field in config and not isinstance(config[field], bool):
            raise ValidationError(f"{field} must be true or false")
    for field in ("state_map", "assignees", "priority_map"):
        if field in config and (
            not isinstance(config[field], dict)
            or any(not isinstance(key, str) or not isinstance(value, str) for key, value in config[field].items())
        ):
            raise ValidationError(f"{field} must map source IDs to text values")
    if any(
        value not in ("urgent", "high", "medium", "low", "none") for value in config.get("priority_map", {}).values()
    ):
        raise ValidationError("Priority mappings must use urgent, high, medium, low or none")
    if any(not isinstance(value, (str, dict, bool)) for value in config.values()):
        raise ValidationError("Invalid configuration value")
    for field in set(config) - {"sync", "notify", "state_map", "assignees", "priority_map"}:
        if not isinstance(config[field], str):
            raise ValidationError(f"{field} must contain text")
    if provider == "github" and not re.fullmatch(r"[\w.-]+/[\w.-]+", config.get("repository", "")):
        raise ValidationError("Repository must be owner/name")
    if provider == "jira":
        if not re.fullmatch(r"https://[a-zA-Z0-9-]+\.atlassian\.net", config.get("site", "")):
            raise ValidationError("Jira site must be https://<tenant>.atlassian.net")
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", config.get("project_key", "")):
            raise ValidationError("Jira project key is required")
        if config.get("estimate_field") and not re.fullmatch(r"customfield_\d+", config["estimate_field"]):
            raise ValidationError("Estimate field must be a Jira customfield ID")
    if provider == "slack" and not all(
        re.fullmatch(r"[A-Z0-9]+", config.get(key, "")) for key in ("team_id", "channel_id")
    ):
        raise ValidationError("Slack team and channel IDs are required")
    return config


def connection_data(connection):
    return {
        "id": str(connection.id),
        "provider": connection.provider,
        "config": connection.config,
        "active": connection.active,
    }


def job_data(job):
    return {
        "id": str(job.id),
        "status": job.status,
        "operation": job.operation,
        "processed": job.processed,
        "error": job.error,
        "updated_at": job.updated_at,
    }
