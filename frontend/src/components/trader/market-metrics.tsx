'use client';
import type { Analytics } from '@/lib/contracts';
import { decimal, fmt, time } from '@/lib/exact';
import { Metric } from '../ui';
export function MarketMetrics({ analytics }: { analytics: Analytics }) {
  return (
    <div className="grid-2">
      <Metric
        label="Last-100-fill VWAP"
        value={decimal(analytics.vwap_ticks)}
        detail={`${analytics.window_fills} fills · ${time(analytics.as_of)} UTC · ticks`}
      />
      <Metric
        label="Volume in [95, 105]"
        value={fmt(analytics.band_volume)}
        detail="Executed units · inclusive price band"
      />
    </div>
  );
}
