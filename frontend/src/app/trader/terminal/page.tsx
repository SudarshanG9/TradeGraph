'use client';
import { useRef } from 'react';
import {
  InstrumentSelector,
  MissingInstrument,
  usePreview,
  useResource,
} from '@/components/preview-provider';
import type { InstrumentInfo, Trade } from '@/lib/contracts';
import { mergeExecutions } from '@/lib/executions';
import { Badge, DataState, Notice, Refresh } from '@/components/ui';
import { OrderBook } from '@/components/trader/order-book';
import { PriceChart } from '@/components/trader/price-chart';
import { OrderForm } from '@/components/trader/order-form';
import { MarketMetrics } from '@/components/trader/market-metrics';
import { ExecutionsTable } from '@/components/trader/executions-table';
function TerminalContent({ instrument }: { instrument: InstrumentInfo }) {
  const { api, mock, liveState } = usePreview();
  const observed = useRef<Trade[]>([]);
  const book = useResource(
    (signal) => api.market.book(instrument.symbol, signal),
    [instrument.id],
    1500,
  );
  const trades = useResource(
    async (signal) => {
      const result = await api.market.trades(instrument.symbol, { limit: 100 }, signal);
      if (signal.aborted) throw new DOMException('Aborted', 'AbortError');
      observed.current = mergeExecutions(observed.current, result.items, instrument.id);
      return { ...result, items: observed.current };
    },
    [instrument.id],
    1500,
  );
  const analytics = useResource(
    (signal) => api.market.analytics(instrument.symbol, '0', '9007199254740991', signal),
    [instrument.id],
    1500,
  );
  return (
    <>
      <h1 className="sr-only">Trading Terminal</h1>
      <div className="terminal-toolbar">
        <div className="toolbar">
          <InstrumentSelector />
          <Badge>Tick size {instrument.tick_size} minor / tick</Badge>
          <Badge>Lot size {instrument.lot_size} units</Badge>
        </div>
        <div className="toolbar">
          <span className="caption">
            {mock
              ? 'Mock market data'
              : liveState === 'live'
                ? 'Live notifications · HTTP snapshots'
                : 'Updates delayed · polling fallback'}
          </span>
          <Refresh
            onClick={() => {
              book.reload();
              trades.reload();
              analytics.reload();
            }}
            loading={book.loading || trades.loading || analytics.loading}
          />
        </div>
      </div>
      {book.data?.stale && (
        <div className="mb-4">
          <Notice tone="warning">
            Depth is stale. A quiet market can have an old snapshot; derived quotes do not guarantee
            execution.
          </Notice>
        </div>
      )}
      <div className="terminal-grid">
        <DataState {...book} retry={book.reload}>
          {book.data && <OrderBook book={book.data} />}
        </DataState>
        <div className="stack terminal-center">
          <DataState {...trades} retry={trades.reload}>
            {trades.data && <PriceChart trades={trades.data.items} />}
          </DataState>
          <DataState {...analytics} retry={analytics.reload}>
            {analytics.data && <MarketMetrics analytics={analytics.data} />}
          </DataState>
          <DataState {...trades} retry={trades.reload}>
            {trades.data && (
              <ExecutionsTable mode="terminal" trades={trades.data.items.slice(0, 3)} />
            )}
          </DataState>
          <p className="caption">
            Latest 100 executions per refresh; retains up to 1,000 observed executions in this view.
            No unobserved trades are inferred.
          </p>
        </div>
        <OrderForm key={instrument.id} />
      </div>
    </>
  );
}
export default function Terminal() {
  const { instrument } = usePreview();
  return instrument ? (
    <TerminalContent key={instrument.id} instrument={instrument} />
  ) : (
    <>
      <h1>Trading Terminal</h1>
      <MissingInstrument />
    </>
  );
}
