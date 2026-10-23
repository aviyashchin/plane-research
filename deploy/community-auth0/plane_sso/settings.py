# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Community Edition with company SSO; native Plane authorization stays intact."""
import json
import os

from plane.settings.production import *  # noqa: F403

ROOT_URLCONF = "plane_sso.urls"
INSTALLED_APPS += ("plane_sso",)
AUTH0_ISSUER = os.environ["AUTH0_ISSUER"]
AUTH0_CLIENT_ID = os.environ["AUTH0_CLIENT_ID"]
AUTH0_CLIENT_SECRET = os.environ["AUTH0_CLIENT_SECRET"]
AUTH0_BASE_URL = os.environ["AUTH0_BASE_URL"]
AUTH0_MANAGEMENT_URL = os.environ["AUTH0_MANAGEMENT_URL"]
AUTH0_DIRECTORY_CLIENT_ID = os.environ["AUTH0_DIRECTORY_CLIENT_ID"]
AUTH0_DIRECTORY_CLIENT_SECRET = os.environ["AUTH0_DIRECTORY_CLIENT_SECRET"]
AUTH0_ORGANIZATION_WORKSPACES = json.loads(os.environ["AUTH0_ORGANIZATION_WORKSPACES"])
WEB_URL = APP_BASE_URL = AUTH0_BASE_URL
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_AGE = 86400
SESSION_COOKIE_SECURE = CSRF_COOKIE_SECURE = True
SESSION_SAVE_EVERY_REQUEST = False
CSRF_TRUSTED_ORIGINS = [AUTH0_BASE_URL]
CSRF_FAILURE_VIEW = "plane_sso.views.csrf_failure"
# One SSO session serves the app and God Mode. Native instance-admin checks remain.
MIDDLEWARE = [
    "django.contrib.sessions.middleware.SessionMiddleware"
    if item == "plane.authentication.middleware.session.SessionMiddleware" else item
    for item in MIDDLEWARE
]
MIDDLEWARE.insert(MIDDLEWARE.index("django.contrib.auth.middleware.AuthenticationMiddleware") + 1,
                  "plane_sso.access.CompanyAccessMiddleware")
