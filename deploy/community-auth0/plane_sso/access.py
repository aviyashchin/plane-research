# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Require company identity, then retain every native Community permission check."""
from urllib.parse import urlsplit

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.utils import timezone
from rest_framework.exceptions import AuthenticationFailed
from plane.api.middleware.api_authentication import APIKeyAuthentication
from plane.db.models import Account

from .directory import require_member
from .models import LoginGrant

PUBLIC = {"/auth/auth0/check/", "/auth/auth0/", "/auth/auth0/callback/", "/auth/auth0/logout/",
          "/auth/sign-out/", "/auth/spaces/sign-out/", "/auth/get-csrf-token/",
          "/api/instances/admins/sign-out/"}
DISABLED_CREDENTIALS = {"/api/instances/admins/sign-in/", "/api/instances/admins/sign-up/",
                        "/api/instances/email-credentials-check/"}


def require_sso_session(request):
    identity = request.session.get("auth0", {})
    if (not request.user.is_authenticated or not request.user.is_active or request.user.is_bot
            or identity.get("issuer") != settings.AUTH0_ISSUER
            or identity.get("organization") not in settings.AUTH0_ORGANIZATION_WORKSPACES
            or identity.get("deadline", 0) <= timezone.now().timestamp()):
        raise PermissionDenied("Subconscious SSO required")
    if not LoginGrant.objects.filter(pk=identity.get("grant"), organization=identity["organization"],
                                    consumed=True, revoked=False, expires_at__gt=timezone.now()).exists():
        raise PermissionDenied("SSO session expired")
    if not Account.objects.filter(user=request.user, provider="auth0", provider_account_id=identity.get("sub"),
                                  metadata__issuer=settings.AUTH0_ISSUER).exists():
        raise PermissionDenied("SSO identity mismatch")
    require_member(identity["sub"], identity["organization"])


def require_api_identity(request, *, asset=False):
    if not asset and not request.path.startswith("/api/v1/"):
        raise PermissionDenied("Native API keys require the versioned API")
    result = APIKeyAuthentication().authenticate(request)
    if result is None:
        raise PermissionDenied("API key required")
    user, _ = result
    if user.is_bot:
        raise PermissionDenied("Company identity required")
    account = Account.objects.filter(user=user, provider="auth0", metadata__issuer=settings.AUTH0_ISSUER).first()
    if account is None or len(settings.AUTH0_ORGANIZATION_WORKSPACES) != 1:
        raise PermissionDenied("Company identity required")
    require_member(account.provider_account_id, next(iter(settings.AUTH0_ORGANIZATION_WORKSPACES)))


class CompanyAccessMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if ((request.path.startswith("/auth/") and request.path not in PUBLIC)
                or request.path in DISABLED_CREDENTIALS):
            return JsonResponse({"error": "Use Subconscious SSO"}, status=403)
        public = request.path in PUBLIC or (request.path == "/api/instances/" and request.method in ("GET", "HEAD"))
        if not public:
            try:
                if request.headers.get("Authorization"):
                    raise PermissionDenied("Use a native API key or SSO session")
                if request.headers.get("X-Api-Key"):
                    require_api_identity(request)
                else:
                    require_sso_session(request)
            except (PermissionDenied, AuthenticationFailed):
                return JsonResponse({"error": "Subconscious SSO required"}, status=401)
            if request.method not in ("GET", "HEAD", "OPTIONS") and not request.headers.get("X-Api-Key"):
                origin = request.headers.get("Origin")
                referer = request.headers.get("Referer")
                if origin is None and referer:
                    parsed = urlsplit(referer)
                    origin = parsed.scheme + "://" + parsed.netloc
                # Native collaboration sends authenticated server-to-server requests without Origin.
                # Browser cross-site writes carry Origin; cookies are Secure and SameSite=Lax.
                if origin is not None and origin != settings.AUTH0_BASE_URL:
                    return JsonResponse({"error": "Untrusted request origin"}, status=403)
        response = self.get_response(request)
        if not request.path.startswith("/static/"):
            response["Cache-Control"] = "private, no-store"
        return response
