'use client';
import type { Account } from '@/lib/contracts';
import { fmt } from '@/lib/exact';
import { Metric } from '../ui';
export function AccountSummary({
  account,
  withPnl = true,
}: {
  account: Account;
  withPnl?: boolean;
}) {
  const pnl = account.positions.reduce((s, p) => s + BigInt(p.realized_pnl), 0n);
  return (
    <div className={withPnl ? 'grid-4' : 'grid-3'}>
      <Metric
        label="Available Cash"
        value={fmt(account.cash_balance)}
        detail="Synthetic funds · minor units"
      />
      <Metric
        label="Reserved Escrow"
        value={fmt(account.escrow_balance)}
        detail="Collateral reserved for orders"
      />
      <Metric
        label="Total Cash + Escrow"
        value={fmt(BigInt(account.cash_balance) + BigInt(account.escrow_balance))}
        detail="Combined cash · minor units"
      />
      {withPnl && (
        <Metric
          label="Gross Realized PnL"
          value={fmt(pnl, true)}
          detail="From settled positions · minor units"
          positive={pnl >= 0n}
        />
      )}
    </div>
  );
}
