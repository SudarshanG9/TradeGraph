'use client';
import type { Book } from '@/lib/contracts';
import { fmt, time } from '@/lib/exact';
import { Badge, Card, Empty, Table } from '../ui';
export function OrderBook({ book }: { book: Book }) {
  const rows = Array.from(
    { length: Math.min(20, Math.max(book.bids.length, book.asks.length)) },
    (_, i) => ({ bid: book.bids[i], ask: book.asks[i] }),
  );
  return (
    <Card title={`Order Book — ${book.symbol}`} className="order-book">
      <Table label="Order book" headers={['Bid', 'Qty', 'Ask', 'Qty']}>
        {rows.map(({ bid, ask }, i) => (
          <tr key={i}>
            <td className="mono positive">{bid ? fmt(bid.price_ticks) : '—'}</td>
            <td className="mono">{bid ? fmt(bid.quantity) : '—'}</td>
            <td className="mono negative">{ask ? fmt(ask.price_ticks) : '—'}</td>
            <td className="mono">{ask ? fmt(ask.quantity) : '—'}</td>
          </tr>
        ))}
      </Table>
      {!rows.length && <Empty message="No resting orders." />}
      <div className="panel-note">
        <Badge tone={book.stale ? 'amber' : 'muted'}>
          {book.stale ? 'Stale depth' : 'Observed depth'}
        </Badge>
        <p className="caption" style={{ marginTop: 8 }}>
          Top 20 levels per side · Price ticks
          <br />
          As of {time(book.as_of)} UTC · v{book.version}
        </p>
      </div>
    </Card>
  );
}
