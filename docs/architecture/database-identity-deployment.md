# Separate database identity deployment

The user approved this boundary after reviewing recovery-persistence-proposals.md.
No new relational table or persisted field is added. Production defaults to
DATABASE_IDENTITY_MODE=isolated and fails closed if credentials are incomplete.
Explicit legacy mode exists only for pre-migration compatibility and does not claim
DB tenant isolation. No live migration or credential change was performed here.

The API uses three separate NOINHERIT/NOBYPASSRLS logins: financial matching and
internal simulator reads, auth credential lookup, and compliance administration.
Financial login cannot read password hashes or SET ROLE compliance_admin_role;
auth login cannot read financial rows. Compliance must explicitly assume its role
and cannot directly modify financial tables. Trader-owned reads use a separate
login named tg_<existing trader UUID>, selected after JWT/actor verification from
a private server-only manifest. RLS derives identity from session_user; arbitrary
app.trader_id/app.role changes cannot switch the actual authenticated login.

RLS is enabled/forced on margin_account, order, order_history, position and durable
request identities. Trader reads are read-only transactions and require exact login
binding. A missing/invalid/broadly-readable credential file fails closed. Each
connection closes after its transaction; no trader context is pooled or inherited.
Financial procedures retain their existing locks/constraints/SECURITY DEFINER owner;
market-wide public execution feeds remain intentional API functionality.

Provisioning is an operator task, never an HTTP endpoint. For a fresh isolated test
DB with the earlier additive migrations installed, select unique audit role names:

```sh
POSTGRES_DB=<isolated-db> PYTHONPATH=. .venv/bin/python scripts/setup_database_identity.py \
  --database <isolated-db> --manifest /private/path/identities.json \
  --financial-role <unique-financial-login> --auth-role <unique-auth-login> \
  --compliance-role <unique-compliance-login> --apply
```

Without --apply this is a dry run. Existing role credentials are never reset.
Reapplication requires the same private manifest, validates role attributes, and
preserves passwords. The file is atomically written mode 0600, binds the database,
and contains server-only service and trader credentials; keep it out of Git/logs.
Run verification without printing credentials:

```sh
PYTHONPATH=. .venv/bin/python scripts/run_isolated.py \
  --manifest /private/path/identities.json --redis-url redis://127.0.0.1:6379/15 \
  -- .venv/bin/python -m pytest -q
```

Use a dedicated empty Redis database; do not flush shared databases. Native fixture
helpers provision/remove only their newly generated trader logins. They are not
called by ordinary API admission. Production user provisioning must run the same
reviewed administrative role/secret workflow when adding a trader.

For deployment, stop new admissions through controlled maintenance, drain financial
and derived work, reconcile active orders, apply the isolated-role/RLS template,
provision every trader read identity, and configure all service credentials and
manifest path together before starting one owner. Do not mix an old shared-query
API with the new policies. The ordinary installer does not deploy this security
migration automatically. Review grants for the selected deployment and its owner
before cutover; financial and compliance credentials remain privileged trusted
service boundaries, not end-user identities.

Rollback: stop traffic/drain connections, apply the reviewed down migration, restore
explicit legacy API credentials/config and prior grants, then verify financial
invariants before restarting one owner. Financial/request rows remain intact.
Rollback intentionally removes stronger DB read isolation; never describe it as
retaining tenant protection. Retire new roles separately after connections stop.

The boundary requires real password authentication. Provisioning verifies that
incorrect passwords are rejected for every service/trader login; startup repeats
that check for service identities and verifies the exact financial policies,
forced RLS and role privileges. A trust-authenticated connection is rejected.
Native proof uses a separate UTF8 PostgreSQL cluster on loopback port 55432 with
SCRAM; the original shared cluster's trust rules were inspected but not changed.
For non-loopback deployment, configure the reviewed PostgreSQL authentication and
transport policy before provisioning credentials. The legacy shared-role installer
now requires explicit legacy mode and cannot silently deploy mixed grants.

Tests requiring administrative fixtures in the separate SCRAM test cluster may
supply `--admin-password-file /private/path/admin-password` to run_isolated.py.
This is a private test-fixture credential, not a production runtime fallback.
Ordinary API connections always supply their explicit service/trader passwords.
