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
  const account = useResource((signal) => api.account.get(signal), [], 5000);
  const orders = useResource((signal) => api.orders.list({ limit: 3 }, signal), [], 5000);
  const trades = useResource(
    (signal) =>
      instrument
        ? api.market.trades(instrument.symbol, { limit: 2 }, signal)
        : Promise.resolve({ items: [], next_before_id: null }),
    [instrument?.id],
    5000,
  );
  const reload = () => {
    account.reload();
    orders.reload();
    trades.reload();
  };
  return (
    <>
      <Heading
        title="Dashboard"
        description="Your available funds, settled positions and recent orders."
      >
        <Refresh onClick={reload} />
      </Heading>
      <div className="stack">
        <DataState {...account} retry={account.reload}>
          {account.data && (
            <>
              <AccountSummary account={account.data} />
              <PositionsTable positions={account.data.positions} />
            </>
          )}
        </DataState>
        <DataState {...orders} retry={orders.reload}>
          {orders.data && <RecentOrders orders={orders.data.items} />}
        </DataState>
        <DataState {...trades} retry={trades.reload}>
          {trades.data && (
            <ExecutionsTable
              trades={trades.data.items}
              action={
                <Link className="link" href="/trader/terminal">
                  Open Trading Terminal →
                </Link>
              }
            />
          )}
        </DataState>
      </div>
    </>
  );
}
