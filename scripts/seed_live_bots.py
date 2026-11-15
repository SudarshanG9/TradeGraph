#!/usr/bin/env python3
"""Explicit administrative provisioning; never invoked by application startup."""
from dataclasses import dataclass
import argparse
import hashlib
from pathlib import Path
import secrets
import sys

import bcrypt
from psycopg.rows import dict_row

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.verify_schema import db_connect


@dataclass(frozen=True)
class BotSpec:
    email: str
    name: str
    strategy: str

    @property
    def pan_hash(self):
        return hashlib.sha256(('tradegraph-live-bot-v1:' + self.email).encode()).hexdigest()


def load_bot_specs():
    """Immutable, exact identity allowlist; no request may extend this namespace."""
    kinds = ('mm-01', 'mm-02', 'mm-03', 'noise-01', 'noise-02', 'noise-03',
             'momentum-01', 'reversion-01')
    return tuple(BotSpec(f'sim-live-{kind}@tradegraph.test',
                         f'Synthetic Live {kind}', kind.rsplit('-', 1)[0]) for kind in kinds)


def inspect_existing_bots(conn, specs):
    """Read-only, complete association validation; missing identities return None."""
    if tuple(specs) != load_bot_specs():
        raise ValueError('Only the approved live bot definitions are permitted')
    result = {}
    with conn.cursor(row_factory=dict_row) as cur:
        for spec in specs:
            cur.execute('''SELECT u.id AS user_id,u.role,t.id AS trader_id,t.full_name,
                d.name AS desk_name,m.trader_id AS margin_id,f.tier_name,
                k.trader_id AS kyc_id,k.pan_hash
                FROM user_account u LEFT JOIN trader t ON t.user_account_id=u.id
                LEFT JOIN desk d ON d.id=t.desk_id
                LEFT JOIN margin_account m ON m.trader_id=t.id
                LEFT JOIN fee_tier f ON f.id=m.fee_tier_id
                LEFT JOIN kyc_profile k ON k.trader_id=t.id WHERE u.email=%s''', (spec.email,))
            row = cur.fetchone()
            if row is not None and not (
                row['role'] == 'TRADER' and row['trader_id'] and row['margin_id']
                and row['kyc_id'] and row['full_name'] == spec.name
                and row['desk_name'] == 'Equities' and row['tier_name'] == 'STANDARD'
                and row['pan_hash'] == spec.pan_hash
            ):
                raise ValueError(f'Conflicting or incomplete synthetic identity: {spec.email}')
            result[spec.email] = row
    return result


def provision_missing_bots(conn, specs, initial_cash=10_000_000):
    if type(initial_cash) is not int or not 1 <= initial_cash <= 100_000_000:
        raise ValueError('Initial cash must be between 1 and 100000000 minor units')
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(hashtext('tradegraph-live-bot-provision'))")
        existing = inspect_existing_bots(conn, specs)
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT id FROM desk WHERE name='Equities'")
            desk = cur.fetchone()
            cur.execute("SELECT id FROM fee_tier WHERE tier_name='STANDARD'")
            tier = cur.fetchone()
            if not desk or not tier:
                raise ValueError('Existing Equities desk and STANDARD fee tier required')
            for spec in specs:
                if existing[spec.email] is not None:
                    continue
                # Plaintext exists only as a transient bcrypt input; never returned or logged.
                hashed = bcrypt.hashpw(secrets.token_urlsafe(36).encode(), bcrypt.gensalt()).decode()
                cur.execute('INSERT INTO user_account(email,password_hash,role) VALUES (%s,%s,\'TRADER\') RETURNING id',
                            (spec.email, hashed))
                uid = cur.fetchone()['id']
                cur.execute('INSERT INTO trader(user_account_id,desk_id,full_name) VALUES (%s,%s,%s) RETURNING id',
                            (uid, desk['id'], spec.name))
                tid = cur.fetchone()['id']
                cur.execute('INSERT INTO kyc_profile(trader_id,pan_hash) VALUES (%s,%s)', (tid, spec.pan_hash))
                cur.execute('INSERT INTO margin_account(trader_id,cash_balance,fee_tier_id) VALUES (%s,%s,%s)',
                            (tid, initial_cash, tier['id']))
        return inspect_existing_bots(conn, specs)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--dry-run', action='store_true', help='Read-only inspection (default)')
    mode.add_argument('--apply', action='store_true', help='Explicitly create missing synthetic accounts')
    parser.add_argument('--initial-cash', type=int, default=10_000_000)
    args = parser.parse_args(argv)
    try:
        with db_connect() as conn:
            if not args.apply:
                conn.read_only = True
            specs = load_bot_specs()
            result = (provision_missing_bots(conn, specs, args.initial_cash) if args.apply
                      else inspect_existing_bots(conn, specs))
            for email, row in result.items():
                print(email, 'valid' if row else 'missing')
        print('Apply committed' if args.apply else 'Dry run: no changes')
    except Exception:
        # Do not expose driver exception parameters (which can contain password hashes).
        raise SystemExit('Bot provisioning failed; no changes committed. Check identities and database configuration.') from None


if __name__ == '__main__':
    main()
