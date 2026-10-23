from plane.settings.community_sso import *  # noqa: F403

SECRET_KEY = "disposable-community-sso-test-secret"
AUTH0_ISSUER = "https://issuer.example/"
AUTH0_BASE_URL = "https://testserver"
AUTH0_ORGANIZATION_WORKSPACES = {"org_company": "company"}
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
CELERY_TASK_ALWAYS_EAGER = True
