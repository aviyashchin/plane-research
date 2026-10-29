# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Login flow lifetime survives Django's session-key rotation."""
import uuid

from django.db import models


class LoginGrant(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.CharField(max_length=255)
    expires_at = models.DateTimeField(db_index=True)
    revoked = models.BooleanField(default=False)
    consumed = models.BooleanField(default=False)
