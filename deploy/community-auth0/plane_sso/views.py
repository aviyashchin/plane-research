# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from datetime import timedelta
from urllib.parse import urlencode, urlsplit

from authlib.integrations.django_client import OAuth
from authlib.integrations.base_client.errors import OAuthError
from joserfc.errors import JoseError
import requests
from rest_framework.exceptions import AuthenticationFailed
from django.conf import settings
from django.contrib.auth import logout
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import HttpResponse, HttpResponseRedirect, JsonResponse
from django.middleware.csrf import get_token
from django.utils import timezone
from django.utils.html import format_html, format_html_join
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods, require_GET, require_POST
from plane.authentication.utils.login import user_login

from .directory import require_member
from .identity import bind_identity
from .models import LoginGrant

FLOW_COOKIE = "plane-auth0-flow"


def csrf_failure(request, reason=""):
    return HttpResponse("Request verification failed", status=403)


def client():
    oauth = OAuth()
    app = oauth.register("auth0", client_id=settings.AUTH0_CLIENT_ID,
                         client_secret=settings.AUTH0_CLIENT_SECRET,
                         server_metadata_url=settings.AUTH0_ISSUER + ".well-known/openid-configuration",
                         client_kwargs={"scope": "openid profile email", "code_challenge_method": "S256",
                                        "token_endpoint_auth_method": "client_secret_post"}, default_timeout=3)
    metadata = app.load_server_metadata()
    if metadata.get("issuer") != settings.AUTH0_ISSUER:
        raise PermissionDenied("Unexpected identity authority")
    authority = urlsplit(settings.AUTH0_ISSUER)
    for endpoint in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
        parsed = urlsplit(metadata.get(endpoint, ""))
        if (parsed.scheme, parsed.netloc) != (authority.scheme, authority.netloc) or parsed.fragment or parsed.username:
            raise PermissionDenied("Unexpected identity endpoint")
    app.server_metadata["id_token_signing_alg_values_supported"] = ["RS256"]
    return app


def revoke_login(request):
    grant_ids = {request.session.get("auth0_grant"), request.get_signed_cookie(
        FLOW_COOKIE, default=None, salt="plane-auth0-logout", max_age=86400)}
    grant_ids.discard(None)
    # UPDATE serializes with callback completion, including a response arriving late.
    LoginGrant.objects.filter(pk__in=grant_ids).update(revoked=True)


@require_GET
def csrf_token(request):
    return JsonResponse({"csrf_token": get_token(request)})


def safe_destination(value):
    if not isinstance(value, str) or any(ord(char) < 32 for char in value) or "\\" in value:
        return None
    parsed = urlsplit(value)
    roots = tuple("/" + slug + "/" for slug in settings.AUTH0_ORGANIZATION_WORKSPACES.values()) + ("/god-mode/",)
    if parsed.scheme or parsed.netloc or not parsed.path.startswith(roots):
        return None
    return value


@csrf_protect
@require_http_methods(["GET", "POST"])
def sign_in(request):
    if request.method == "GET":
        destination = safe_destination(request.GET.get("next") or request.GET.get("next_path"))
        if destination:
            request.session["auth0_destination"] = destination
        from .access import require_sso_session
        try:
            require_sso_session(request)
        except PermissionDenied:
            pass
        else:
            return HttpResponseRedirect(destination or "/" + next(iter(settings.AUTH0_ORGANIZATION_WORKSPACES.values())) + "/")
        options = format_html_join("", '<option value="{}">{}</option>',
                                   settings.AUTH0_ORGANIZATION_WORKSPACES.items())
        return HttpResponse(format_html(
            '<!doctype html><title>Plane — Subconscious SSO</title><h1>Plane Community</h1>'
            '<form method="post"><input type="hidden" name="csrfmiddlewaretoken" value="{}">'
            '<label>Company <select name="organization">{}</select></label>'
            '<button type="submit">Continue with Subconscious SSO</button></form>'
            '<form method="post" action="/auth/auth0/logout/">'
            '<input type="hidden" name="csrfmiddlewaretoken" value="{}">'
            '<button type="submit">Sign out of Plane</button>'
            '<button type="submit" name="shared" value="1">Sign out of Auth0 SSO</button></form>',
            get_token(request), options, get_token(request)))
    organization = request.POST.get("organization")
    if organization not in settings.AUTH0_ORGANIZATION_WORKSPACES:
        raise PermissionDenied("Company access denied")
    destination = request.session.get("auth0_destination")
    revoke_login(request)
    request.session.flush()
    if destination:
        request.session["auth0_destination"] = destination
    grant = LoginGrant.objects.create(organization=organization, expires_at=timezone.now() + timedelta(hours=24))
    request.session["auth0_grant"] = str(grant.pk)
    request.session["auth0_pending_organization"] = organization
    response = client().authorize_redirect(request, settings.AUTH0_BASE_URL + "/auth/auth0/callback/",
                                           organization=organization)
    response.set_signed_cookie(FLOW_COOKIE, str(grant.pk), salt="plane-auth0-logout", secure=True,
                               httponly=True, samesite="Lax", max_age=86400, path="/auth/")
    return response


@require_GET
def callback(request):
    organization = request.session.pop("auth0_pending_organization", None)
    try:
        if organization not in settings.AUTH0_ORGANIZATION_WORKSPACES:
            raise PermissionDenied("No company login in progress")
        token = client().authorize_access_token(request, leeway=0, claims_options={
            "iss": {"essential": True, "value": settings.AUTH0_ISSUER},
            "aud": {"essential": True, "value": settings.AUTH0_CLIENT_ID},
            "sub": {"essential": True}, "exp": {"essential": True},
            "org_id": {"essential": True, "value": organization},
        })
        claims = token["userinfo"]
        require_member(claims["sub"], organization, fresh=True)
        with transaction.atomic():
            grant = LoginGrant.objects.select_for_update().filter(pk=request.session.get("auth0_grant"),
                         organization=organization, revoked=False, consumed=False, expires_at__gt=timezone.now()).first()
            if grant is None:
                raise PermissionDenied("Login revoked")
            user, workspace = bind_identity(claims, organization)
            user_login(request, user, is_app=True)
            deadline = timezone.now() + timedelta(hours=24)
            request.session.set_expiry(deadline)
            request.session["auth0"] = {"issuer": settings.AUTH0_ISSUER, "sub": claims["sub"],
                                    "organization": organization, "workspace": str(workspace.pk),
                                    "deadline": deadline.timestamp(), "grant": str(grant.pk)}
            request.session.save()
            grant.consumed = True
            grant.save(update_fields=["consumed"])
        destination = request.session.pop("auth0_destination", None)
        return HttpResponseRedirect(destination or "/" + workspace.slug + "/")
    except (OAuthError, JoseError, requests.RequestException, KeyError, ValueError, PermissionDenied):
        request.session.flush()
        return HttpResponse("Company sign in denied", status=403)


@csrf_protect
@require_POST
def sign_out(request):
    revoke_login(request)
    logout(request)
    location = "/auth/auth0/"
    if request.POST.get("shared") == "1":
        location = settings.AUTH0_ISSUER + "v2/logout?" + urlencode({
            "client_id": settings.AUTH0_CLIENT_ID, "returnTo": settings.AUTH0_BASE_URL + "/auth/auth0/"})
    response = HttpResponseRedirect(location)
    response.delete_cookie(FLOW_COOKIE, path="/auth/", samesite="Lax")
    return response


@require_GET
def browser_access(request):
    """Gate native HTML without replacing the upstream Community applications."""
    from .access import require_api_identity, require_sso_session
    try:
        original_path = urlsplit(request.headers.get("X-Forwarded-Uri", "")).path
        bucket = "/" + settings.AWS_STORAGE_BUCKET_NAME
        if request.headers.get("X-Api-Key") and (original_path == bucket or original_path.startswith(bucket + "/")):
            require_api_identity(request, asset=True)
        else:
            require_sso_session(request)
    except (PermissionDenied, AuthenticationFailed):
        target = "/auth/auth0/"
        destination = safe_destination(request.headers.get("X-Forwarded-Uri"))
        if destination:
            target += "?" + urlencode({"next": destination})
        return HttpResponseRedirect(target)
    if original_path.startswith("/god-mode/"):
        from plane.license.models import InstanceAdmin
        if not InstanceAdmin.objects.filter(user=request.user).exists():
            return HttpResponse("Instance administrator access required", status=403)
    return HttpResponse(status=204)
