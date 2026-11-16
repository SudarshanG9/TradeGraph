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
