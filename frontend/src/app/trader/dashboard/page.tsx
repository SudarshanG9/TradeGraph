'use client';
import Link from 'next/link';
import { usePreview, useResource } from '@/components/preview-provider';
import { DataState, Heading, Refresh } from '@/components/ui';
import { AccountSummary } from '@/components/trader/account-summary';
import { PositionsTable } from '@/components/trader/positions-table';
import { RecentOrders } from '@/components/trader/recent-orders';
import { ExecutionsTable } from '@/components/trader/executions-table';
export default function Dashboard() {
  const { api, instrument } = usePreview();
  const r = useResource(
    async (signal) => {
      const [account, orders, trades] = await Promise.all([
        api.account.get(signal),
        api.orders.list({ limit: 3 }, signal),
        instrument
          ? api.market.trades(instrument.symbol, { limit: 2 }, signal)
          : Promise.resolve({ items: [], next_before_id: null }),
      ]);
      return { account, orders, trades };
    },
    [instrument?.id],
    5000,
  );
  return (
    <>
      <Heading
        title="Dashboard"
        description="Your available funds, settled positions and recent orders."
      >
        <Refresh onClick={r.reload} loading={r.loading} />
      </Heading>
      <DataState {...r} retry={r.reload}>
        {r.data && (
          <div className="stack">
            <AccountSummary account={r.data.account} />
            <div className="dashboard-tables">
              <PositionsTable positions={r.data.account.positions} />
              <RecentOrders orders={r.data.orders.items} />
            </div>
            <ExecutionsTable
              trades={r.data.trades.items}
              action={
                <Link className="link" href="/trader/terminal">
                  Open Trading Terminal →
                </Link>
              }
            />
          </div>
        )}
      </DataState>
    </>
  );
}
