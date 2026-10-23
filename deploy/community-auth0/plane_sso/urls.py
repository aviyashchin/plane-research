from django.urls import include, path
from .views import browser_access, callback, csrf_token, sign_in, sign_out

urlpatterns = [
    path("auth/auth0/check/", browser_access, name="sso-browser-access"),
    path("auth/auth0/", sign_in, name="auth0-sign-in"),
    path("auth/auth0/callback/", callback, name="auth0-callback"),
    path("auth/auth0/logout/", sign_out, name="auth0-logout"),
    path("auth/sign-out/", sign_out, name="sso-sign-out"),
    path("auth/spaces/sign-out/", sign_out, name="sso-space-sign-out"),
    path("api/instances/admins/sign-out/", sign_out, name="sso-admin-sign-out"),
    path("auth/get-csrf-token/", csrf_token, name="sso-csrf-token"),
    path("", include("plane.urls")),
]
