import type { HealthResponse } from '@/lib/contracts';
import { Card } from '../ui';
export function HealthCards({ health }: { health: HealthResponse }) {
  return (
    <div className="grid-4">
      {[
        ['PostgreSQL', health.dependencies.postgres === 'up'],
        ['Redis', health.dependencies.redis === 'up'],
        ['Neo4j', health.dependencies.neo4j === 'up'],
        ['Trading Engine', health.trading_ready],
      ].map(([label, up]) => (
        <Card key={String(label)} className="padded health-card">
          <div className="row-between">
            <p>{label}</p>
            <i className={up ? 'status-up' : 'status-down'} />
          </div>
          <strong>
            {up ? (label === 'Trading Engine' ? 'Available' : 'Connected') : 'Unavailable'}
          </strong>
          <p className="caption">
            {label === 'Trading Engine' ? 'Mock trading readiness' : 'Mock dependency state'}
          </p>
        </Card>
      ))}
    </div>
  );
}
