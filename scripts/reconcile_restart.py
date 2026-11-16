"""Read-only restart diagnostics. Never takes ownership or changes orders/balances."""
import json
from backend.config import Settings
from backend.stores.postgres import Database


def diagnose(database):
    with database.connect() as conn:
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        counts=conn.execute('''SELECT count(*) AS total_orders,
          count(*) FILTER (WHERE status IN ('OPEN','PARTIAL')) AS active_orders
          FROM public."order"''').fetchone()
        counts.update(conn.execute('SELECT count(*) AS execution_count FROM execution').fetchone())
        counts.update(conn.execute('''SELECT count(*) AS volume_mismatches FROM public."order" o
          WHERE o.filled_quantity<>(SELECT coalesce(sum(e.quantity),0) FROM execution e
          WHERE e.buy_order_id=o.id OR e.sell_order_id=o.id)''').fetchone())
        counts.update(conn.execute("""SELECT count(*) AS matching_owner_locks FROM pg_locks
          WHERE locktype='advisory' AND database=(SELECT oid FROM pg_database WHERE datname=current_database()) AND classid=((hashtext('tradegraph-matching-owner')::bigint >> 32) & 4294967295)
          AND objid=(hashtext('tradegraph-matching-owner')::bigint & 4294967295) AND granted""").fetchone())
    safe=not any(counts[k] for k in ('active_orders','volume_mismatches','matching_owner_locks'))
    return counts | {'cold_start_safe':safe,'mode':'read_only',
        'requirements':[] if safe else ['Preserve current ownership and financial data; operator reconciliation required'],
        'limitation':'No persisted in-flight matching/outbox state; active orders require operator reconciliation, never automatic cancellation'}


if __name__=='__main__':
    print(json.dumps(diagnose(Database(Settings.from_env())),indent=2))
