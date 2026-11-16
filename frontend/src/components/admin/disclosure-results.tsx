'use client';
import type { Search } from '@/lib/contracts';
import { date } from '@/lib/exact';
import { useSymbolFor } from '../trader/positions-table';
import { Card, Empty, Table } from '../ui';
export function DisclosureResults({ results }: { results: Search | null }) {
  const symbolFor = useSymbolFor();
  return (
    <Card>
      <Table
        label="Disclosure results"
        headers={['Rank', 'Disclosure title / ID', 'Instrument', 'Published']}
      >
        {results?.items.map((d) => (
          <tr key={d.id}>
            <td className="mono muted">
              {d.rank.toFixed(2)}
              <span className="progress-track" aria-hidden="true">
                <span style={{ width: `${Math.max(0, Math.min(100, d.rank * 100))}%` }} />
              </span>
            </td>
            <td className="wrap">
              <strong>{d.title}</strong>
              <span className="caption mono"> · #{d.id}</span>
            </td>
            <td>{d.instrument_id === null ? '—' : symbolFor(d.instrument_id)}</td>
            <td className="muted">{date(d.published_at)}</td>
          </tr>
        ))}
      </Table>
      {!results ? (
        <Empty message="Enter a search query to retrieve disclosure metadata." />
      ) : (
        !results.items.length && <Empty message="No disclosures match your query." />
      )}
      <div className="panel-note">
        Showing titles and metadata only — full disclosure text viewing is not available in this
        build. Search and ranking are provided by PostgreSQL full-text search.
      </div>
    </Card>
  );
}
