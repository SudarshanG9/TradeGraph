'use client';
import { useEffect, useState } from 'react';
import type { Int } from '@/lib/contracts';
import { InstrumentSelector, usePreview, useResource } from '@/components/preview-provider';
import { DataState, Heading, Pagination } from '@/components/ui';
import { VwapPanel, PriceBandPanel } from '@/components/trader/analytics-panels';
import { ExecutionsTable } from '@/components/trader/executions-table';
export default function Analytics() {
  const { api, instrument } = usePreview();
  const [cursors, setCursors] = useState<(Int | undefined)[]>([undefined]);
  useEffect(() => {
    setCursors([undefined]);
  }, [instrument.id]);
  const cursor = cursors.at(-1);
  const r = useResource(async () => {
    const [analytics, trades] = await Promise.all([
      api.market.analytics(instrument.symbol, '95', '105'),
      api.market.trades(instrument.symbol, { limit: 4, before_id: cursor }),
    ]);
    return { analytics, trades };
  }, [instrument.id, cursor]);
  return (
    <>
      <Heading
        title="Market Analytics"
        description="In-memory analytical structures computed from settled executions."
      >
        <InstrumentSelector />
      </Heading>
      <div className="stack">
        <DataState {...r} retry={r.reload}>
          {r.data && (
            <div className="stack">
              <div className="grid-2">
                <VwapPanel analytics={r.data.analytics} symbol={instrument.symbol} />
                <PriceBandPanel />
              </div>
              <ExecutionsTable mode="analytics" trades={r.data.trades.items}>
                <Pagination
                  canPrevious={cursors.length > 1}
                  canNext={!!r.data.trades.next_before_id}
                  previous={() => setCursors((c) => c.slice(0, -1))}
                  next={() => {
                    const id = r.data!.trades.next_before_id;
                    if (id) setCursors((c) => [...c, id]);
                  }}
                  loading={r.loading}
                />
              </ExecutionsTable>
            </div>
          )}
        </DataState>
      </div>
    </>
  );
}
