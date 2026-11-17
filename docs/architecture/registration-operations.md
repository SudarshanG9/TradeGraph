# Registration operations

Registration is additive. Apply identity/request migrations first, then (with an
operator connection, never FastAPI credentials):

```sh
.venv/bin/python -m scripts.migrate_registration --database YOUR_DATABASE --auth-role YOUR_AUTH_ROLE
.venv/bin/python -m scripts.migrate_registration --database YOUR_DATABASE --auth-role YOUR_AUTH_ROLE --apply
```

The dry run changes nothing. Application checks the explicit DB matches libpq's
selected DB. The transaction rejects existing `lower(btrim(email))` duplicates.
Preflight: `SELECT lower(btrim(email)),count(*) FROM user_account GROUP BY 1 HAVING count(*)>1;`
Resolve conflicting identities manually before retrying; never delete automatically.
Normalization is ASCII email, lowercase, trimming ASCII spaces in both login and
signup. Hashes use supported bcrypt, 12..72 characters and <=72 UTF-8 bytes.

Default policy creates zero-funded PENDING_VERIFICATION users. Email delivery is
not implemented. No email is claimed sent and no KYC row is fabricated. These
accounts cannot log in or trade. Deploy a reviewed verification workflow before
using public registration for actual verified identities.

For a synthetic demonstration explicitly add `--synthetic-demo --starter-cash 20000`.
This records an operator-selected demo policy, bypasses email verification only
for synthetic trading, and creates PENDING_PROVISIONING accounts. It makes no KYC
claim. Browser requests cannot supply funding, roles, tiers or verification status.
New accounts use STANDARD, no desk, zero escrow and the fixed policy funds.

The auth DB login can execute only a pinned-search-path SECURITY DEFINER account
creation function and read registration status; it cannot create PostgreSQL roles
or directly write financial tables. Public /register returns an opaque receipt and
status after COMMIT. Duplicate signup returns 409 REGISTRATION_EXISTS; a timeout is
ambiguous: sign in with the same email/password to reconcile; do not change email
and automatically retry. Pending status is disclosed only after password checking.

Rollback: stop signup traffic; apply
`db/migrations/20261116_user_registration.down.sql` using the operator connection.
It removes the callable function and preserves accounts, registration state, policy
and uniqueness. Never deploy a backend without readiness checks while pending or
disabled registrations exist. Retained tables can be removed only by a separately
reviewed data migration after all states have been reconciled.

After synthetic registration, run the trusted operator reconciler with the same
private identity manifest and explicit admin connection used during setup:

```sh
.venv/bin/python -m scripts.provision_registrations --database YOUR_DATABASE
.venv/bin/python -m scripts.provision_registrations --database YOUR_DATABASE --apply
```

Run it again to recover interrupted provisioning. It locks the manifest and uses
a database advisory lock; credentials are atomically staged (0600/fsync/rename)
before CREATE ROLE. A crash before/after role COMMIT can use the same staged secret.
It verifies wrong-password rejection, session_user, NOINHERIT/nonadministrative
memberships, actual margin access and cross-user RLS before ACTIVE. Failure leaves
FAILED_RETRYABLE and preserves the account. Never delete credential manifests to
recover a provisioning failure. Run with an operator identity, never a public API
identity. PENDING_VERIFICATION is deliberately ineligible; no invented verification.

Per-trader roles cost one catalog entry/secret per user and a connection handshake
per read context. Dozens are exercised; hundreds/thousands need measured connection
capacity, role/manifest backup and serialization review. This does not replace RLS
with browser-controlled tenant variables or claim unmeasured scale.

## Local signup without approval

The local runner now starts a separate trusted registration worker. It applies
`20261117_registration_no_approval.sql`, moves existing PENDING_VERIFICATION traders
to automatic setup and verifies their database identities before ACTIVE. Disabled
accounts remain disabled. Funding policy and KYC records are unchanged. New trader
signups require no human approval. Administrator accounts remain operator-created.

Run the same local command as before. For test-stack layouts, the runner discovers
the owner-only `admin-password` file beside the identity manifest. Otherwise supply
`--provision-admin-password-file /private/path/to/password` or set
`REGISTRATION_ADMIN_PASSWORD_FILE`. Operator credentials go only to the separate
worker; FastAPI, Next and the proxy receive no operator password. Setup retries
bounded batches every two seconds and preserves failed registrations for retry.
The UI reports automatic setup rather than pending approval.

This supersedes the verification-gate instructions above for the local runner.
For another deployment, run `python -m scripts.auto_provision_registrations` as a
trusted operator service with the same explicit database configuration. Do not
provide database role-creation privileges to the public API.

Validation for automatic signup: 25 real PostgreSQL registration/authorization tests passed; 53 frontend tests passed (two optional Redis cases skipped), TypeScript and formatting passed. A separate production build passed without replacing the running server assets. The existing local runner had one active order, so it was not restarted. A temporary parent-bound worker enables automatic activation now; the updated runner owns this worker on subsequent starts. Rebuild the frontend and restart the runner only after active orders are resolved.
