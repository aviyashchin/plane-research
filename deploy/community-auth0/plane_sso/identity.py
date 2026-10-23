"""Resolve verified issuer and subject before considering an email address."""

import hashlib
import uuid

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.validators import validate_email
from django.db import connection, transaction
from plane.db.models import Account, Profile, User, Workspace, WorkspaceMember


def verified_identity(claims, organization):
    subject = claims.get("sub")
    email = claims.get("email")
    if not isinstance(email, str):
        raise PermissionDenied("Verified email required")
    email = email.strip().lower()
    if (claims.get("iss") != settings.AUTH0_ISSUER or claims.get("org_id") != organization
            or not isinstance(subject, str) or not subject or len(subject) > 255
            or claims.get("email_verified") is not True or len(email) > 255):
        raise PermissionDenied("Verified identity required")
    try:
        validate_email(email)
    except ValidationError:
        raise PermissionDenied("Verified email required") from None
    return subject, email


@transaction.atomic
def bind_identity(claims, organization):
    subject, email = verified_identity(claims, organization)
    # Serializes simultaneous callbacks, including case-insensitive email collisions.
    # All callbacks take identity lock before email lock; no reverse lock order exists.
    for kind, value in (("subject", subject), ("email", email)):
        lock = int.from_bytes(hashlib.sha256((kind + value).encode()).digest()[:8], signed=True)
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", [lock])
    account = Account.objects.select_for_update().filter(provider="auth0", provider_account_id=subject).first()
    user = account.user if account else None
    if account and account.metadata.get("issuer") != settings.AUTH0_ISSUER:
        raise PermissionDenied("Identity binding conflict")
    collision = User.objects.filter(email__iexact=email)
    if user:
        collision = collision.exclude(pk=user.pk)
        if not user.is_active or user.is_bot:
            raise PermissionDenied("Inactive identity")
    if collision.exists():
        raise PermissionDenied("Email binding conflict; verified account linking required")
    workspace = Workspace.objects.filter(slug=settings.AUTH0_ORGANIZATION_WORKSPACES[organization]).first()
    if workspace is None:
        raise PermissionDenied("Company workspace unavailable")
    if user is None:
        user = User(username=uuid.uuid4().hex, email=email, is_email_verified=True)
        user.set_unusable_password()
        user.save()
        Account.objects.create(user=user, provider="auth0", provider_account_id=subject,
                               access_token="", refresh_token="", metadata={"issuer": settings.AUTH0_ISSUER})
    elif user.email != email:
        user.email = email
        user.is_email_verified = True
        user.save(update_fields=["email", "is_email_verified"])
    membership, _ = WorkspaceMember.objects.get_or_create(workspace=workspace, member=user, defaults={"role": 15})
    if not membership.is_active:
        raise PermissionDenied("Inactive company membership")
    # Company admission and workspace creation are managed outside Plane's signup flow.
    Profile.objects.update_or_create(user=user, defaults={"is_onboarded": True})
    return user, workspace
