# Plane research fork

This fork restores publicly released Plane capabilities on stable Plane v1.4.2.
The fork is for controlled research. Production rollout is outside this change.

## Source revisions

| Source                                                                                                    | Revision                                   | Use                                               |
| --------------------------------------------------------------------------------------------------------- | ------------------------------------------ | ------------------------------------------------- |
| [Plane v1.4.2](https://github.com/makeplane/plane/tree/5f7d92784c403f76284f0f16718f320221dc7fec)          | `5f7d92784c403f76284f0f16718f320221dc7fec` | Maintained application base                       |
| [Plane v0.7.1-dev](https://github.com/makeplane/plane/tree/02111d779b1fb4fb7a5765ab23f594045b8147df)      | `02111d779b1fb4fb7a5765ab23f594045b8147df` | Earlier AI, analytics and Gantt feature reference |
| [Plane v0.16-dev](https://github.com/makeplane/plane/tree/c1b1ba35c161fccd6f833fad212326f4032738eb)       | `c1b1ba35c161fccd6f833fad212326f4032738eb` | Integration and importer reference                |
| [Integration removal](https://github.com/makeplane/plane/commit/a852e3cc523bf368635d4c91cb76ecdeb98defaf) | `a852e3cc523bf368635d4c91cb76ecdeb98defaf` | Public removal boundary                           |

The early snapshot used Apache-2.0. The later snapshot and current base use AGPL-3.0.
This fork retains current AGPL notices and the root license.
Public availability does not establish a license for unrelated enterprise code.
No current proprietary enterprise source or license bypass is included.

Historical import workers forwarded requests to a separate proxy service.
That service is absent from the public snapshot.
Consequently, historical cherry-picks alone cannot restore working importers.

The fork reuses current issues, pages, comments, estimates, permissions, Timeline,
analytics, Django, Celery, requests, cryptography and the installed OpenAI client.
The new provider adapters replace the missing proxy inside the existing API and worker.
The MIT [gh-plane-sync](https://github.com/mggarofalo/gh-plane-sync) utility was assessed.
Its separate cron and SQLite state do not meet native setup and recovery requirements.
No additional sidecar or dependency is required.

## Available flows

Open **Workspace settings → Integrations**, then select a project.
Only workspace administrators can open this setup screen.
Existing issue and page editors retain AI entry points for members.

- AI assistance drafts, rewrites, summarizes, and reads an accessible project page.
  Select a page by name. Review and edit generated text before creating an issue.
  Generation alone does not write an issue.
- GitHub and Jira imports show a source sample and known limitations before starting.
  Jobs show progress and support **Resume** after failure or worker loss.
- GitHub sync imports issue content and comments. Plane owns state after import.
  Sync exports native project issues and EXTERNAL comments only after explicit opt-in.
  Native rich documents remain intact after export. Internal comments remain private.
- Slack supports installed bot credentials, project/channel mapping, signed slash commands,
  and project issue notifications. Notifications update one message per issue.
- Research analytics adds numeric estimate totals, state/priority grouping,
  cycle/module/state-group filters, and CSV export.
  Existing analytics charts remain available.
- Existing Timeline/Gantt views remain the scheduling surface for issues, cycles and modules.
  Existing date edits, bar dragging and resizing use native persistence.

## Operator setup

Use the repository's existing self-hosted setup and database backup process.
Set these variables on **both API and Celery worker**, then run migrations:

```sh
# Generate once. Store securely and retain with encrypted database backups.
python3 -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
# Set the output as RESEARCH_CREDENTIAL_KEY in the deployment secret configuration.
python manage.py migrate --noinput
```

`RESEARCH_CREDENTIAL_KEY` encrypts provider credentials at rest.
Losing or replacing the key requires reconnecting providers.
Do not put the key in source control or copy it into browser configuration.
Keep `SECRET_KEY` stable: signed sync markers use that key for replay recovery.

Local inference is the default research configuration:

```dotenv
LLM_PROVIDER=openai
LLM_BASE_URL=http://ollama:11434/v1
LLM_MODEL=<installed-local-model>
```

Upgraded instances can retain AI settings in the database.
With the default `SKIP_ENV_VAR=1`, saved `LLM_MODEL` and `LLM_PROVIDER` override environment values.
Set the installed model in the existing instance-admin AI settings before using local inference.
The saved provider must be `openai` for Ollama's compatible API.
Alternatively, set `SKIP_ENV_VAR=0` to use environment configuration.
That option applies to all instance settings. Carry existing settings into deployment variables first.

The API must reach the model URL. `localhost` inside a container means that container.
Ollama uses its [OpenAI-compatible API](https://docs.ollama.com/api/openai-compatibility).
Model names are operator-selected. The client uses a 90-second timeout and a 2048-token output limit.
Use a local model with enough capacity for the research task.
Paid provider endpoints require explicit operator configuration.
Without a custom base URL, `LLM_ALLOW_PAID_API=1` is required.
No paid inference was used for this implementation's QA.

### Provider setup

Connections use installed tokens. OAuth app installation is not implemented.
The connection's repository, Jira project, or Slack channel cannot be changed.
Use another Plane project for another source. Reconnect the same source to replace credentials.
Disconnect erases credentials and prevents queued jobs from processing.
Import receipts remain for replay and audit purposes.

**GitHub:** enter `owner/repository` and a token with issue read access.
Sync also requires issue write access. Enable sync only for a repository where export is intended.
For a GitHub App, provide a current installation token and replace the token before expiry.
Automatic GitHub App token renewal is not implemented.
Create an [issue and issue-comment webhook](https://docs.github.com/en/webhooks/using-webhooks/creating-webhooks).
Use the displayed payload URL and the same webhook secret.
[GitHub signature validation](https://docs.github.com/en/webhooks/using-webhooks/validating-webhook-deliveries)
requires `X-Hub-Signature-256` and a delivery ID.

**Jira Cloud:** enter `https://<tenant>.atlassian.net`, project key, account email and API token.
The account needs Browse Projects and comment access.
Imports use [enhanced JQL search](https://developer.atlassian.com/cloud/jira/platform/rest/v3/api-group-issue-search/).
Set `estimate_field` to the tenant's numeric story-point custom field ID.

**Slack:** install an app with `chat:write` and `commands` permissions in a test workspace.
Add the bot to the selected channel. Enter bot token, team ID, channel ID and signing secret.
Create `/plane` with the displayed request URL. The command text becomes a native issue.
The receiver checks the [Slack signature and request age](https://docs.slack.dev/authentication/verifying-requests-from-slack/).
The public callback must reach the API over HTTPS for external provider tests.

Field mappings accept JSON objects. Example:

```json
{
  "state_map": { "10001": "<state-in-this-project>" },
  "assignees": { "<source-account-id>": "<existing-project-member-id>" },
  "priority_map": { "1": "urgent", "2": "high" },
  "estimate_field": "customfield_10016"
}
```

`priority_map` and `estimate_field` apply to Jira only.
GitHub source user IDs are decimal account IDs. Jira uses accountId values.
Unknown users are left unassigned. Imports never send invitations.
Unmapped source statuses create project states.

### Recovery and ownership

The database stores source IDs, per-item progress, provider delivery IDs and outbound receipts.
Workers acknowledge tasks after processing. PostgreSQL locks serialize each connection.
Duplicate deliveries and imports reuse existing native records.
A failed job exposes a sanitized error and a Resume action.
GET requests retry transient failures. Writes use persisted identities and signed markers where available.
Slack uses a stable client message ID, but Slack controls deduplication after uncertain network delivery.
This is not a transactional guarantee across external providers.

Keep the existing Celery worker running with the API deployment.
After a worker restart, use Resume if the broker did not redeliver an unfinished job.
Check token scopes, rate limits, field mapping and numeric estimate configuration before retrying.
A GitHub event currently scans the mapped repository. Large repositories need workload measurement before rollout.
GitHub sync has explicit ownership: GitHub controls imported content; Plane controls state.
Native content remains owned by Plane. Sync does not promise arbitrary field merging.

## Import limitations

The preview discloses these limits before importing:

- Attachment URLs become native source links. Attachment binaries are not copied.
  Source permissions and URL expiry still apply.
- Rich text becomes escaped plain text. Custom fields are omitted except numeric estimates.
- Parent, Blocks, Duplicate and Relates links are restored when both issues are imported.
  Custom link types and links outside the selected source project are omitted.
- Historical activity logs are omitted. Source comment author names appear in comment text.
- Pull requests are excluded from GitHub issue imports.
- Jira Server and Data Center are not supported by the Cloud adapter.

These are research adapters, not a claim of current enterprise feature parity.

## Verification

Run the existing required commands:

```sh
pnpm install --frozen-lockfile
pnpm check --concurrency=2
pnpm build --concurrency=2
docker compose -f docker-compose-test.yml up --build --abort-on-container-exit --exit-code-from api-tests
```

`Research fork checks` runs on PRs targeting `research-base-v1.4.2`, including drafts.
CI checks changed Python files, real migration upgrades, and the full isolated API suite.
The MinIO test image is pinned because the previous unversioned image could not be pulled.

Contract tests exercise 12 imported issues, six completed issues, 30 estimate points,
comments, relations, source mappings, retries, signatures and cross-workspace rejection.
Provider HTTP boundaries use fixtures. Provider fixture tests do not prove live account setup.
Live GitHub read/import and local-model checks are separate from Slack/Jira account checks.
Live Slack/Jira checks require the operator's test workspace credentials and public callback.
