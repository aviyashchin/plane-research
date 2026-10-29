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

Build the company-branded web, administrator, and Spaces applications from this
exact source revision with Node 22 and the repository's pinned pnpm. Product
labels and icons use Subconscious assets. Upstream copyright, package names,
and AGPL license notices remain intact. The login page and Help menu link to
this modified source. Paid-edition labels identify commercial offerings;
branding does not unlock paid features or enable optional AI providers.

```sh
corepack pnpm --filter web... --filter admin... --filter space... install --frozen-lockfile --ignore-scripts
NODE_OPTIONS=--max-old-space-size=6144 VITE_AUTH0_SSO=1 VITE_ADMIN_BASE_PATH=/god-mode VITE_SPACE_BASE_PATH=/spaces VITE_WEBSITE_URL=https://subconscious.ai VITE_SUPPORT_EMAIL=avi@subconscious.ai corepack pnpm turbo run build --filter=web --filter=admin --filter=space --concurrency=1
mkdir -p /path/to/plane-deployment/auth0/{web-build,admin-build,space-build}
rsync -a --delete apps/web/build/client/ /path/to/plane-deployment/auth0/web-build/
rsync -a --delete apps/admin/build/client/ /path/to/plane-deployment/auth0/admin-build/
rsync -a --delete apps/space/build/ /path/to/plane-deployment/auth0/space-build/
```

Do not run the build and type-check Turbo tasks concurrently: both rebuild
shared package output directories.

Back up the database and upload volume before installing or upgrading. Then:

```sh
sudo docker compose --project-name plane-community --env-file plane.env build api admin web space
sudo docker compose --project-name plane-community --env-file plane.env run --rm --no-deps --entrypoint python api manage.py migrate plane_sso --noinput
sudo docker compose --project-name plane-community --env-file plane.env run --rm --no-deps --entrypoint python api manage.py link_auth0_administrator owner@example.com
sudo docker compose --project-name plane-community --env-file plane.env up -d --no-deps api admin web space proxy
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

## Optional company-domain HTTPS ingress

`compose.public.yml` is an explicit additional Compose file. The default
installation keeps loopback ingress. The public edge uses the existing Caddy
image and routes every request through the same authenticated proxy. All
backing-service ports remain private. Caddy provisions and renews the domain
certificate using persistent TLS volumes. No external load balancer is needed.

Before enabling public ingress:

1. Create an A record for `projects.subconscious.ai` at the existing EC2 public
   address. Preserve unrelated DNS records and the main marketing website.
2. Append `https://projects.subconscious.ai/auth/auth0/callback/` and
   `https://projects.subconscious.ai/auth/auth0/` to the existing Auth0 client's
   callback and logout URL lists. Preserve existing pilot entries. Set the
   application's display name to `Subconscious Projects`.
3. Set `AUTH0_BASE_URL` and `WEB_URL` to `https://projects.subconscious.ai`,
   `CORS_ALLOWED_ORIGINS` to the same origin, and `APP_DOMAIN` to the hostname.
   Public and private origins use separate host-only cookies; the public origin
   becomes canonical for login and writes.
4. Allow inbound TCP ports 80 and 443 in the instance security group. Do not
   expose API, database, Redis, RabbitMQ, MinIO, or private development ports.
5. Recreate the application services after the origin change, then start:

```sh
sudo docker compose --project-name plane-community --env-file plane.env -f docker-compose.yml -f docker-compose.override.yml -f auth0/compose.public.yml up -d public-edge
```

Check real DNS and a trusted HTTPS certificate before reporting a public URL.
Verify anonymous API/object denial, Auth0 authorization entry and callback,
Avi's native administrator identity, project writes, and upload/download.
The EC2 address is not an Elastic IP; a stop/start can require a DNS update.
Keep the AWS storage upgrade paused.

Recovery: the deployment backup archives `auth0/` recursively, including all
three built applications and public ingress configuration. On a recovery host,
build `api`, `admin`, `web`, and `space` from the archived Dockerfiles/artifacts.
TLS certificates can be reissued after DNS points to the recovery host.
