# Full Community with existing Auth0

This deployment overlay retains the complete upstream Plane Community v1.4.2
web, admin, live, space, worker and data services. The small AGPL backend adapter
uses Auth0 Universal Login for authentication. Native Plane roles still control
all projects, work items, cycles, modules, views, pages and instance settings.
No paid license, trial or pilot route allowlist is required. A deployment-only
God Mode flag redirects expired sessions to SSO instead of the disabled password
form. All native Community screens and controls remain available.

Plane's maintained native OIDC integration is a paid-edition feature:
https://developers.plane.so/self-hosting/govern/oidc-sso . This overlay therefore
reuses the existing company's confidential Auth0 client and read-only directory
client. It does not enable vendor paid features.

## Install and operate

Copy this directory to `auth0/` beside the existing upstream `docker-compose.yml`
and `plane.env`. Copy `compose.sso.yml` to `docker-compose.override.yml` so ordinary
Compose commands always include SSO. Keep the Compose project name unchanged.
Create mode-0600 `auth0.env` containing these server-only settings:

```dotenv
AUTH0_BASE_URL=https://plane.example.com
AUTH0_ISSUER=https://auth.example.com/
AUTH0_MANAGEMENT_URL=https://tenant.us.auth0.com/
AUTH0_CLIENT_ID=existing-confidential-client
AUTH0_CLIENT_SECRET=from-existing-client
AUTH0_DIRECTORY_CLIENT_ID=existing-read-only-directory-client
AUTH0_DIRECTORY_CLIENT_SECRET=from-existing-directory-client
AUTH0_ORGANIZATION_WORKSPACES='{"org_existing":"existing-workspace-slug"}'
```

The directory client needs `read:users` and `read:organizations` with permission
to read user organization memberships. Do not add tenant-management privileges.
Register `${AUTH0_BASE_URL}/auth/auth0/callback/` as a client callback and
`${AUTH0_BASE_URL}/auth/auth0/` as an allowed logout URL. Preserve other entries.
Use HTTPS, loopback ingress and the existing private network boundary.

Build the native admin app from this exact source revision with Node 22 and the
repository's pinned pnpm. The flag changes only sign-in recovery:

```sh
corepack pnpm --filter admin... install --frozen-lockfile --ignore-scripts
NODE_OPTIONS=--max-old-space-size=4096 VITE_AUTH0_SSO=1 VITE_ADMIN_BASE_PATH=/god-mode corepack pnpm turbo run build --filter=admin --concurrency=1
cp -a apps/admin/build/client /path/to/plane-deployment/auth0/admin-build
```

Back up the database and upload volume before installing or upgrading. Then:

```sh
sudo docker compose --project-name plane-community --env-file plane.env build api admin
sudo docker compose --project-name plane-community --env-file plane.env run --rm --no-deps --entrypoint python api manage.py migrate plane_sso --noinput
sudo docker compose --project-name plane-community --env-file plane.env run --rm --no-deps --entrypoint python api manage.py link_auth0_administrator owner@example.com
sudo docker compose --project-name plane-community --env-file plane.env up -d --no-deps api admin proxy
```

The explicit linking command requires an existing active native account and one
verified, unblocked Auth0 member of the configured company. The command grants
native workspace, existing-project and instance administrator roles. Browser
login never links accounts by email and never grants administrator access.
New company members receive native member role 15. Existing native roles remain.

`/` and `/god-mode/` enter SSO. The same secure session serves both applications.
Caddy checks native HTML and every object upload/download before proxying.
Native signed file URLs also require a current company session or bound API key.
Caddy pins the HTTPS forwarding header because the private ingress terminates TLS.
Native work-item and page links survive SSO through validated relative destinations. Password,
magic-link and alternate-provider login routes are disabled. Browser writes
with an Origin or Referer must match the configured application origin. Native
collaboration forwards server requests without Origin. Secure SameSite=Lax
cookies protect cross-site browser requests. Versioned native API keys require
an active human user's bound Auth0 identity and current company membership.

Signed code flow uses PKCE, state, nonce, issuer, audience, expiry and organization
checks. Live company membership is checked at login and cached for at most 15
seconds thereafter. Company removal denies subsequent API calls; existing live
connections follow upstream reauthorization behavior. Sessions expire after
24 hours. Logout revokes the local grant and pending callback. Optional shared
logout also ends the Auth0 session. Auth0 and directory outages fail closed.

Upstream public Spaces and unauthenticated sharing are inaccessible behind the
company gate. No external AI, SMTP or paid provider is configured by this overlay.

## Validation and recovery

```sh
sudo docker compose --project-name plane-community --env-file plane.env run --rm --no-deps --entrypoint python api manage.py test sso_tests --settings=plane.settings.community_sso_tests --noinput --keepdb
sudo docker compose --project-name plane-community --env-file plane.env ps -a
sudo docker compose --project-name plane-community --env-file plane.env logs --tail=100 api proxy
```

The focused suite uses a separate PostgreSQL test database and actual native API
views. Tests cover work-item persistence, administrator access, revoked grants,
password-only sessions, origin checks and SSO browser entry. Hosted Auth0 browser
verification is a separate deployment check; mocked directory tests cannot prove
provider login. Credentials, browser state and receipts stay outside Git.

Never use `down -v`. Restore database and uploads together after data loss.
Retain the SSO overlay during rollback; removing the overlay reopens native
password login. Local backups cannot protect against loss of the host disk.
Keep backup scheduling and off-host retention in the machine's private runbook.
