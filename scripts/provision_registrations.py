"""Operator-owned one-shot reconciler; no admin credentials enter the API runtime."""
import argparse
from backend.config import Settings
from backend.services.trader_provisioning import provision_trader_identity
from scripts.verify_schema import db_connect


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database',required=True)
    parser.add_argument('--trader-id')
    parser.add_argument('--limit',type=int,default=100)
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    if not 1<=args.limit<=1000:parser.error('Limit must be 1..1000')
    settings=Settings.from_env()
    with db_connect() as conn:
        if conn.info.dbname!=args.database or settings.postgres_db!=args.database:
            raise ValueError('Explicit database mismatch')
        rows=conn.execute("SELECT trader_id FROM public.registration_state WHERE status IN ('PENDING_PROVISIONING','FAILED_RETRYABLE') AND (%s::uuid IS NULL OR trader_id=%s::uuid) ORDER BY updated_at LIMIT %s",(args.trader_id,args.trader_id,args.limit)).fetchall()
    if not args.apply:
        print(f'Dry run: {len(rows)} eligible registrations; no credentials or accounts changed')
        return
    failures=0
    for row in rows:
        try:provision_trader_identity(row[0],settings,expected_database=args.database)
        except Exception:failures+=1
    print(f'Provisioning complete: {len(rows)-failures} verified, {failures} require operator reconciliation; no credentials logged')
    if failures:raise SystemExit(1)


if __name__=='__main__':main()
