"""Bounded, fail-closed checks against the existing Auth0 directory."""

import hashlib
import time
from urllib.parse import quote

import requests
from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import PermissionDenied


def require_member(subject, organization, *, fresh=False):
    base = settings.AUTH0_MANAGEMENT_URL.rstrip("/") + "/"
    identity = (base, subject, organization, settings.AUTH0_DIRECTORY_CLIENT_ID)
    key = "plane-auth0-member:" + hashlib.sha256(repr(identity).encode()).hexdigest()
    started = time.monotonic()
    deadline = cache.get(key)
    if not fresh and deadline is not None and started < deadline:
        return
    try:
        token = directory_token(base, identity)
        headers = {"Authorization": "Bearer " + token}
        user_url = base + "api/v2/users/" + quote(subject, safe="")
        response = requests.get(user_url, headers=headers, timeout=3, allow_redirects=False)
        if response.status_code != 200:
            raise PermissionDenied("Company authority unavailable")
        response.raise_for_status()
        user = response.json()
        if user.get("user_id") != subject or user.get("blocked", False):
            raise PermissionDenied("Company access denied")
        # Auth0 paginates user organizations. Stop as soon as the expected ID is proven.
        for page in range(100):
            response = requests.get(user_url + "/organizations", headers=headers,
                                    params={"page": page, "per_page": 100}, timeout=3, allow_redirects=False)
            if response.status_code != 200:
                raise PermissionDenied("Company authority unavailable")
            response.raise_for_status()
            organizations = response.json()
            if any(item.get("id") == organization for item in organizations):
                if time.monotonic() - started >= 12:
                    raise PermissionDenied("Company authority timed out")
                cache.set(key, started + 15, timeout=15)
                return
            if len(organizations) < 100 or time.monotonic() - started >= 9:
                break
    except (requests.RequestException, ValueError, KeyError, TypeError, AttributeError):
        raise PermissionDenied("Company authority unavailable") from None
    raise PermissionDenied("Company access denied")


def directory_token(base, identity):
    token_key = "plane-auth0-directory:" + hashlib.sha256(repr(identity[::3]).encode()).hexdigest()
    token = cache.get(token_key)
    if token is None:
        response = requests.post(base + "oauth/token", json={
            "grant_type": "client_credentials",
            "client_id": settings.AUTH0_DIRECTORY_CLIENT_ID,
            "client_secret": settings.AUTH0_DIRECTORY_CLIENT_SECRET,
            "audience": base + "api/v2/",
        }, timeout=3, allow_redirects=False)
        if response.status_code != 200:
            raise PermissionDenied("Company authority unavailable")
        response.raise_for_status()
        payload = response.json()
        token = payload["access_token"]
        cache.set(token_key, token, timeout=max(1, min(300, int(payload["expires_in"]) - 10)))
    return token
