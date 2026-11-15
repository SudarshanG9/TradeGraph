'use client';
import { useMemo, useState } from 'react';
import type { Trade } from '@/lib/contracts';
import { fmt, time } from '@/lib/exact';
import { Badge, Card, Empty } from '../ui';
export function PriceChart({ trades }: { trades: Trade[] }) {
  const [hover, setHover] = useState<number | null>(null);
  const series = useMemo(
    () =>
      [...trades].sort(
        (a, b) =>
          Date.parse(a.executed_at) - Date.parse(b.executed_at) ||
          (BigInt(a.id) < BigInt(b.id) ? -1 : 1),
      ),
    [trades],
  );
  if (!series.length)
    return (
      <Card title="Executed price">
        <Empty message="No execution history. No prices are interpolated." />
      </Card>
    );
  const prices = series.map((t) => BigInt(t.price_ticks)),
    min = prices.reduce((a, b) => (a < b ? a : b)) - 1n,
    max = prices.reduce((a, b) => (a > b ? a : b)) + 1n,
    span = max - min;
  const start = Date.parse(series[0].executed_at),
    end = Date.parse(series.at(-1)!.executed_at),
    width = 560,
    height = 145;
  // Only bounded pixel ratios are converted to Number. Prices and labels remain exact.
  const points = series.map((t, i) => ({
    x: 48 + ((Date.parse(t.executed_at) - start) / Math.max(1, end - start)) * width,
    y: 16 + height - (Number(((prices[i] - min) * 100000n) / span) / 100000) * height,
  }));
  const selected = hover === null ? series.at(-1)! : series[hover];
  const last = series.at(-1)!;
  return (
    <Card className="price-chart">
      <div className="chart-heading">
        <span className="caption">Last Price</span>
        <strong className="mono chart-last">{fmt(last.price_ticks)}</strong>
        <Badge tone="blue">Demo executions</Badge>
      </div>
      <svg
        className="chart"
        viewBox="0 0 660 200"
        role="img"
        aria-label={`Execution price line chart. ${series.length} observed trades. Latest ${last.price_ticks} ticks.`}
        onMouseLeave={() => setHover(null)}
      >
        {[0, 1, 2, 3, 4].map((i) => {
          const value = min + (span * BigInt(i)) / 4n;
          const y = 16 + height - (Number(((value - min) * 100000n) / span) / 100000) * height;
          return (
            <g key={i}>
              <line className="gridline" x1="48" x2="608" y1={y} y2={y} />
              <text x="40" y={y + 3} textAnchor="end">
                {value.toString()}
              </text>
            </g>
          );
        })}
        {[0, 1, 2, 3].map((i) => (
          <g key={i}>
            <line
              className="gridline"
              x1={48 + (i * width) / 3}
              x2={48 + (i * width) / 3}
              y1="16"
              y2="161"
            />
            <text x={48 + (i * width) / 3} y="185" textAnchor="middle">
              {time(new Date(start + ((end - start) * i) / 3).toISOString()).slice(0, 5)}
            </text>
          </g>
        ))}
        <polyline className="price-line" points={points.map((p) => `${p.x},${p.y}`).join(' ')} />
        <line
          x1={48}
          x2={608}
          y1={points.at(-1)!.y}
          y2={points.at(-1)!.y}
          stroke="#3b82f6"
          strokeDasharray="3 5"
          opacity=".4"
        />
        {points.map((p, i) => (
          <circle
            key={series[i].id}
            cx={p.x}
            cy={p.y}
            r={hover === i ? 5 : 4}
            fill={hover === i ? '#e2e8f0' : '#3b82f6'}
            fillOpacity={hover === i ? 1 : 0.01}
            tabIndex={0}
            aria-label={`${series[i].price_ticks} ticks at ${time(series[i].executed_at)} UTC`}
            onFocus={() => setHover(i)}
            onBlur={() => setHover(null)}
            onMouseEnter={() => setHover(i)}
          >
            <title>{`${time(series[i].executed_at)} UTC · ${series[i].price_ticks} ticks · ${series[i].quantity} units`}</title>
          </circle>
        ))}
        <circle cx={points.at(-1)!.x} cy={points.at(-1)!.y} r="3" fill="#3b82f6" />
        <text x="616" y={points.at(-1)!.y + 3} fill="#3b82f6">
          {last.price_ticks}
        </text>
      </svg>
      <div className="chart-tooltip" aria-live="polite">
        {time(selected.executed_at)} UTC · {fmt(selected.price_ticks)} ticks ·{' '}
        {fmt(selected.quantity)} units
      </div>
    </Card>
  );
}
