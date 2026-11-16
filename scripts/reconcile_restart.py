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
        counts.update(conn.execute('''WITH orders AS (
          SELECT id,filled_quantity FROM public."order" UNION ALL
          SELECT id,filled_quantity FROM public.order_history)
          SELECT count(*) AS volume_mismatches FROM orders o
          WHERE o.filled_quantity<>(SELECT coalesce(sum(e.quantity),0) FROM execution e
          WHERE e.buy_order_id=o.id OR e.sell_order_id=o.id)''').fetchone())
        counts.update(conn.execute('''SELECT count(*) AS duplicate_order_ids FROM
          public."order" o JOIN public.order_history h USING(id)''').fetchone())
        counts.update(conn.execute('''SELECT count(*) AS execution_order_mismatches FROM public.execution e
          WHERE NOT EXISTS(SELECT 1 FROM public."order" WHERE id=e.buy_order_id
             UNION ALL SELECT 1 FROM order_history WHERE id=e.buy_order_id)
             OR NOT EXISTS(SELECT 1 FROM public."order" WHERE id=e.sell_order_id
             UNION ALL SELECT 1 FROM order_history WHERE id=e.sell_order_id)''').fetchone())
        counts.update(conn.execute('''SELECT count(*) AS escrow_mismatches FROM margin_account m
          WHERE m.escrow_balance::numeric<>(SELECT coalesce(sum(
            o.price_ticks::numeric*i.tick_size*(o.quantity-o.filled_quantity)+
            ceil(o.price_ticks::numeric*i.tick_size*(o.quantity-o.filled_quantity)*
              greatest(f.maker_fee_bps,f.taker_fee_bps)*0.0001)),0)
            FROM public."order" o JOIN instrument i ON i.id=o.instrument_id
            JOIN fee_tier f ON f.id=m.fee_tier_id
            WHERE o.trader_id=m.trader_id AND o.status IN ('OPEN','PARTIAL'))''').fetchone())
        counts.update(conn.execute('''WITH deltas AS (
          SELECT buy_trader_id AS trader_id,instrument_id,quantity::numeric AS q FROM execution
          UNION ALL SELECT sell_trader_id,instrument_id,-quantity::numeric FROM execution),
          expected AS (SELECT trader_id,instrument_id,sum(q) AS q FROM deltas GROUP BY trader_id,instrument_id)
          SELECT count(*) AS position_mismatches FROM expected e FULL JOIN position p USING(trader_id,instrument_id)
          WHERE coalesce(e.q,0)<>coalesce(p.net_quantity,0)''').fetchone())
        counts.update(conn.execute("""SELECT count(*) AS matching_owner_locks FROM pg_locks
          WHERE locktype='advisory' AND database=(SELECT oid FROM pg_database WHERE datname=current_database()) AND classid=((hashtext('tradegraph-matching-owner')::bigint >> 32) & 4294967295)
          AND objid=(hashtext('tradegraph-matching-owner')::bigint & 4294967295) AND granted""").fetchone())
        installed=conn.execute("SELECT to_regclass('public.event_outbox') IS NOT NULL AS installed").fetchone()['installed']
        counts.update(outbox_pending=0,outbox_retrying=0,historical_observations_missing=0,missing_publication_intents=0)
        if installed:
            counts.update(conn.execute('''SELECT count(*) FILTER(WHERE completed_at IS NULL) AS outbox_pending,
              count(*) FILTER(WHERE completed_at IS NULL AND last_error IS NOT NULL) AS outbox_retrying,
              count(*) FILTER(WHERE consumer='regime' AND payload IS NULL) AS historical_observations_missing
              FROM event_outbox''').fetchone())
            counts.update(conn.execute('''SELECT count(*) AS missing_publication_intents FROM execution e
              CROSS JOIN (VALUES('graph'),('regime')) c(consumer)
              WHERE NOT EXISTS(SELECT 1 FROM event_outbox o WHERE o.execution_id=e.id AND o.consumer=c.consumer)''').fetchone())
        trigger=conn.execute("""SELECT EXISTS(SELECT 1 FROM pg_trigger WHERE tgrelid='public.execution'::regclass
          AND tgname='execution_publication' AND tgenabled IN ('O','A')) AS installed""").fetchone()['installed']
    financial_keys=('active_orders','volume_mismatches','matching_owner_locks','escrow_mismatches',
                    'position_mismatches','duplicate_order_ids','execution_order_mismatches','missing_publication_intents')
    safe=installed and trigger and not any(counts[k] for k in financial_keys)
    actions=[]
    if counts['matching_owner_locks']:
        actions.append('An owner is live: do not launch a second matching process')
    if counts['active_orders']:
        actions.append('Preserve active orders and escrow; reconcile lost admission/match intents before trading; never automatically cancel or rematch')
    if any(counts[k] for k in financial_keys if k not in ('active_orders','matching_owner_locks')):
        actions.append('Financial invariant mismatch: preserve evidence and reconcile against canonical executions; do not change balances automatically')
    if not installed or not trigger:
        actions.append('Install the reviewed additive recovery migration and runtime grants before startup')
    if counts['outbox_pending']:
        actions.append('Resume durable consumers under verified ownership; never resettle an outbox record')
    if counts['historical_observations_missing']:
        actions.append('Historical regime inputs are unavailable: retain missing-observation diagnostics; never synthesize historic depth')
    return counts | {'cold_start_safe':bool(safe),'mode':'read_only','requirements':actions,
        'durable_publication_installed':bool(installed and trigger),
        'pending_financial_operations':'unknown pre-settlement matching intents' if counts['active_orders'] else 'no active orders; committed-state checks only',
        'limitation':'No durable pre-settlement matching/admission journal; active orders require operator reconciliation, never automatic cancellation'}


if __name__=='__main__':
    print(json.dumps(diagnose(Database(Settings.from_env())),indent=2))
