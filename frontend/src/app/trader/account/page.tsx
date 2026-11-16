'use client';
import { usePreview, useResource } from '@/components/preview-provider';
import { DataState, Heading, Refresh } from '@/components/ui';
import { AccountSummary } from '@/components/trader/account-summary';
import { PositionsTable } from '@/components/trader/positions-table';
import { AccountExplanation } from '@/components/trader/account-explanation';
export default function Account() {
  const { api } = usePreview();
  const r = useResource((signal) => api.account.get(signal), [], 5000);
  return (
    <>
      <Heading
        title="Account & Positions"
        description="Available funds, reserved collateral and settled positions."
      >
        <Refresh loading={r.loading} onClick={r.reload} />
      </Heading>
      <DataState {...r} retry={r.reload}>
        {r.data && (
          <div className="stack">
            <AccountSummary account={r.data} withPnl={false} />
            <PositionsTable positions={r.data.positions} details />
            <AccountExplanation />
            <p className="caption mono">Trader ID: {r.data.trader_id}</p>
          </div>
        )}
      </DataState>
    </>
  );
}
