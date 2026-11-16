'use client';
import { usePreview, useResource } from '@/components/preview-provider';
import { DataState, Heading, Refresh } from '@/components/ui';
import { HealthCards } from '@/components/admin/health-cards';
import { InvestigationTools } from '@/components/admin/investigation-tools';
import { SimulatorControls } from '@/components/admin/simulator-controls';
export default function Overview() {
  const { api } = usePreview();
  const r = useResource((signal) => api.health.get(signal), [], 10000);
  return (
    <>
      <Heading
        title="Compliance Overview"
        description="Visibility into trading and database health — order submission is unavailable in this role."
      >
        <Refresh onClick={r.reload} loading={r.loading} />
      </Heading>
      <div className="stack">
        <DataState {...r} retry={r.reload}>
          {r.data && <HealthCards health={r.data} />}
        </DataState>
        <InvestigationTools />
        <SimulatorControls />
      </div>
    </>
  );
}
