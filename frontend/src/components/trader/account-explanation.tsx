import { Notice } from '../ui';
export function AccountExplanation() {
  return (
    <Notice>
      Available cash excludes collateral reserved against orders. Both BUY and SELL reserve cash in
      this academic model; net positions may be negative. Gross realized PnL excludes fees, while
      cash reflects assessed fees. All amounts are exact integer minor units; no currency or decimal
      scale is assumed.
    </Notice>
  );
}
