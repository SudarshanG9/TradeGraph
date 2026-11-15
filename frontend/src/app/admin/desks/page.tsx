'use client';
import { usePreview, useResource } from '@/components/preview-provider';
import { DataState, Heading, Refresh } from '@/components/ui';
import { DeskRollup } from '@/components/admin/desk-rollup';
import { DeskExplanation } from '@/components/admin/desk-explanation';
export default function Desks() {
  const { api } = usePreview();
  const r = useResource(() => api.desks.rollup());
  return (
    <>
      <Heading
        title="Hierarchical Desk Analytics"
        description="A recursive CTE walks the desk hierarchy and aggregates PnL and execution volume exactly once per desk, regardless of depth."
      >
        <Refresh onClick={r.reload} loading={r.loading} />
      </Heading>
      <div className="stack">
        <DataState {...r} retry={r.reload}>
          {r.data && <DeskRollup desks={r.data.items} />}
        </DataState>
        <DeskExplanation />
      </div>
    </>
  );
}
