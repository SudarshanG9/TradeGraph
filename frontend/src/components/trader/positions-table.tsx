'use client';
import { useState } from 'react';
import type { Position } from '@/lib/contracts';
import { fmt } from '@/lib/exact';
import { usePreview } from '../preview-provider';
import { Card, Empty, Table } from '../ui';
export function useSymbolFor() {
  const { instruments } = usePreview();
  return (id: number) => instruments.find((i) => i.id === id)?.symbol ?? `Instrument ${id}`;
}
export function PositionsTable({
  positions,
  details = false,
}: {
  positions: Position[];
  details?: boolean;
}) {
  const symbolFor = useSymbolFor();
  const [selected, setSelected] = useState<number | null>(null);
  const selectedPosition = positions.find((p) => p.instrument_id === selected);
  return (
    <Card title="My Positions">
      <Table
        label="My Positions"
        headers={['Instrument', 'Net Quantity', 'Gross Realized PnL (minor)']}
      >
        {positions.map((p) => (
          <tr key={p.instrument_id}>
            <td>
              {details ? (
                <button className="link" onClick={() => setSelected(p.instrument_id)}>
                  {symbolFor(p.instrument_id)}
                </button>
              ) : (
                <strong>{symbolFor(p.instrument_id)}</strong>
              )}
            </td>
            <td className="mono">{fmt(p.net_quantity, true)}</td>
            <td className={`mono ${BigInt(p.realized_pnl) >= 0n ? 'positive' : 'negative'}`}>
              {fmt(p.realized_pnl, true)}
            </td>
          </tr>
        ))}
      </Table>
      {!positions.length && <Empty message="No settled positions for this account." />}
      {selectedPosition && (
        <div className="panel-note" role="status">
          Instrument ID {selectedPosition.instrument_id} · Net units{' '}
          {fmt(selectedPosition.net_quantity, true)} · PnL basis: {selectedPosition.pnl_basis}.
          Gross realized PnL excludes fees.
        </div>
      )}
    </Card>
  );
}
