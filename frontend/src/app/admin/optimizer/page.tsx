'use client';
import { useState } from 'react';
import type { Optimizer } from '@/lib/contracts';
import { usePreview } from '@/components/preview-provider';
import { Heading, Notice, Skeleton } from '@/components/ui';
import { OptimizerControls } from '@/components/admin/optimizer-controls';
import { PlanPanel } from '@/components/admin/plan-panel';
export default function OptimizerPage() {
  const { fixture } = usePreview();
  const [result, setResult] = useState<Optimizer | null>(null),
    [busy, setBusy] = useState(false);
  const a = result?.plans.forced_sequential['Execution Time'],
    b = result?.plans.automatic['Execution Time'];
  const comparison = (x: number | undefined, y: number | undefined) =>
    x === undefined || y === undefined
      ? undefined
      : x < y
        ? ('FASTER' as const)
        : x > y
          ? ('SLOWER' as const)
          : ('EQUAL' as const);
  return (
    <>
      <Heading
        title="Database Query Optimizer"
        description="Side-by-side PostgreSQL EXPLAIN ANALYZE for an allowlisted query scenario."
      />
      <div className="stack">
        <OptimizerControls onResult={setResult} onBusy={setBusy} />
        {busy || fixture === 'loading' ? (
          <Skeleton />
        ) : (
          <div className="grid-2">
            <PlanPanel
              title="Forced Sequential Plan"
              plan={result?.plans.forced_sequential ?? null}
              dataset={result?.dataset_size}
              rowCount={result?.row_count}
              comparison={comparison(a, b)}
            />
            <PlanPanel
              title="Automatically Selected Plan"
              plan={result?.plans.automatic ?? null}
              dataset={result?.dataset_size}
              rowCount={result?.row_count}
              comparison={comparison(b, a)}
            />
          </div>
        )}
        <Notice tone="warning">
          These are measured plan timings for a specific query and dataset — they do not imply a
          universal performance improvement. Aggregate output rows are distinct from matching
          execution rows.
        </Notice>
      </div>
    </>
  );
}
