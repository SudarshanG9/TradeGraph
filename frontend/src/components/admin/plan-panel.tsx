'use client';
import type { ExplainPlan, Int, PlanNode } from '@/lib/contracts';
import { fmt } from '@/lib/exact';
import { Badge, Card, Empty } from '../ui';
export function PlanTree({ node }: { node: PlanNode }) {
  return (
    <div className="plan-node">
      <details open>
        <summary>
          <span>
            {node['Node Type']}
            {node['Relation Name'] ? ` on ${node['Relation Name']}` : ''}
            {node['Index Name'] ? ` on ${node['Index Name']}` : ''}
          </span>
        </summary>
        <div className="plan-properties">
          {node['Startup Cost'] !== undefined && (
            <p>
              cost={node['Startup Cost']}..{node['Total Cost'] ?? '—'}
            </p>
          )}
          {(['Filter', 'Recheck Cond', 'Index Cond'] as const).map((k) =>
            node[k] ? (
              <p key={k}>
                {k}: {node[k]}
              </p>
            ) : null,
          )}
          {node['Actual Rows'] !== undefined && <p>Actual rows: {fmt(node['Actual Rows'])}</p>}
        </div>
        {node.Plans?.map((child, i) => (
          <PlanTree key={i} node={child} />
        ))}
      </details>
    </div>
  );
}
export function PlanPanel({
  title,
  plan,
  dataset,
  rowCount,
  comparison,
}: {
  title: string;
  plan: ExplainPlan | null;
  dataset?: Int;
  rowCount?: Int;
  comparison?: 'FASTER' | 'SLOWER' | 'EQUAL';
}) {
  const child = plan?.Plan.Plans?.[0];
  return (
    <Card
      title={title}
      action={
        comparison && (
          <Badge
            tone={comparison === 'FASTER' ? 'green' : comparison === 'SLOWER' ? 'amber' : 'muted'}
          >
            {comparison}
          </Badge>
        )
      }
      className="padded plan-panel"
    >
      {!plan ? (
        <Empty message="Compare plans to inspect PostgreSQL EXPLAIN ANALYZE results." />
      ) : (
        <>
          <dl className="plan-stats">
            {[
              [
                'Execution time',
                plan['Execution Time'] === undefined ? '—' : `${plan['Execution Time']} ms`,
              ],
              [
                'Planning time',
                plan['Planning Time'] === undefined ? '—' : `${plan['Planning Time']} ms`,
              ],
              ['Rows returned (aggregate)', rowCount ? fmt(rowCount) : '—'],
              ['Dataset size', dataset ? `${fmt(dataset)} rows` : '—'],
              ['Access method', child?.['Node Type'] ?? plan.Plan['Node Type']],
              [
                'Buffer hits / reads',
                `${plan.Plan['Shared Hit Blocks'] === undefined ? '—' : fmt(plan.Plan['Shared Hit Blocks'])} / ${plan.Plan['Shared Read Blocks'] === undefined ? '—' : fmt(plan.Plan['Shared Read Blocks'])}`,
              ],
            ].map(([label, value]) => (
              <div className="row-between" key={label}>
                <dt>{label}</dt>
                <dd className="mono">{value}</dd>
              </div>
            ))}
          </dl>
          <div className="plan-tree">
            <PlanTree node={plan.Plan} />
          </div>
        </>
      )}
    </Card>
  );
}
