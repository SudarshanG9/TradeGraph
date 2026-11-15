'use client';
import Link from 'next/link';
import { usePreview, useResource } from '@/components/preview-provider';
import { DataState, Heading, Refresh } from '@/components/ui';
import { AccountSummary } from '@/components/trader/account-summary';
import { PositionsTable } from '@/components/trader/positions-table';
import { RecentOrders } from '@/components/trader/recent-orders';
import { ExecutionsTable } from '@/components/trader/executions-table';
export default function Dashboard() {
  const { api } = usePreview();
  const r = useResource(async () => {
    const [account, orders, trades] = await Promise.all([
      api.account.get(),
      api.orders.list({ limit: 3 }),
      api.market.trades('ACME', { limit: 2 }),
    ]);
    return { account, orders, trades };
  });
  return (
    <>
      <Heading
        title="Dashboard"
        description="Welcome back, Alice — here's where your demo account stands."
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
