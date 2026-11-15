import type { Similar } from '@/lib/contracts';
import { time } from '@/lib/exact';
import { symbolFor } from '../trader/positions-table';
import { Card, Empty, Table } from '../ui';
export function RegimeResults({ results }: { results: Similar | null }) {
  return (
    <Card title="Nearest historical snapshots">
      <Table
        label="Similar market regimes"
        headers={[
          'Snapshot',
          'Instrument',
          'Captured (UTC)',
          'Feature vector (six dimensions)',
          'Cosine distance',
        ]}
      >
        {results?.matches.map((r) => (
          <tr key={r.id}>
            <td className="mono">SNP-{r.id}</td>
            <td>{symbolFor(r.instrument_id)}</td>
            <td className="muted">{time(r.captured_at, true)}</td>
            <td className="mono muted">[{r.features.join(', ')}]</td>
            <td className="mono">
              {r.cosine_distance.toFixed(4)}
              <span className="progress-track" aria-hidden="true">
                <span
                  style={{
                    width: `${Math.max(0, Math.min(100, (1 - r.cosine_distance) * 100))}%`,
                    background: 'var(--green)',
                  }}
                />
              </span>
            </td>
          </tr>
        ))}
      </Table>
      {!results ? (
        <Empty message="Run a search to preview historical similarity results." />
      ) : (
        !results.matches.length && (
          <Empty message="No matching snapshots for this instrument and feature query." />
        )
      )}
      <div className="panel-note">
        Six engineered market features, not language-model embeddings — ranked by cosine distance,
        closest first.
      </div>
    </Card>
  );
}
