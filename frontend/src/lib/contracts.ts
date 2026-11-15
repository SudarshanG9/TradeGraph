/** Normalized contracts mirror FastAPI field names. Int is an exact decimal string;
 * wire JSON integer tokens must be parsed losslessly BEFORE normalization. */
export type Int = `${bigint}`;
export type AccountRole = 'TRADER' | 'COMPLIANCE_ADMIN';
export interface LoginRequest {
  email: string;
  password: string;
}
export interface LoginResponse {
  access_token: string;
  token_type: 'bearer';
  role: AccountRole;
  expires_in: number;
}
export interface InstrumentInfo {
  id: number;
  symbol: string;
  tick_size: Int;
  lot_size: Int;
  is_active: boolean;
}
export interface InstrumentCatalog {
  items: InstrumentInfo[];
}
export interface NewOrder {
  instrument_id: number;
  side: 'BUY' | 'SELL';
  price_ticks: Int;
  quantity: Int;
}
export interface AcceptedOrder {
  order_id: Int;
  status: 'OPEN';
  accepted_at: string;
}
export interface OrderSummary extends NewOrder {
  id: Int;
  trader_id: string;
  filled_quantity: Int;
  status: 'OPEN' | 'PARTIAL' | 'FILLED' | 'CANCELLED';
  created_at: string;
  updated_at: string;
  archived: boolean;
}
export interface OwnOrders {
  items: OrderSummary[];
  next_before_id: Int | null;
}
export interface Position {
  instrument_id: number;
  net_quantity: Int;
  realized_pnl: Int;
  pnl_basis: 'gross';
}
export interface Account {
  trader_id: string;
  cash_balance: Int;
  escrow_balance: Int;
  positions: Position[];
}
export interface CancelledOrder {
  order_id: Int;
  status: 'CANCELLED';
  cancelled_quantity: Int;
}
export interface Level {
  price_ticks: Int;
  quantity: Int;
}
export interface Book {
  symbol: string;
  bids: Level[];
  asks: Level[];
  as_of: string | null;
  stale: boolean;
  version: Int;
}
export interface Trade {
  id: Int;
  instrument_id: number;
  buy_order_id: Int;
  sell_order_id: Int;
  buy_trader_id: string;
  sell_trader_id: string;
  price_ticks: Int;
  quantity: Int;
  executed_at: string;
}
export interface Trades {
  items: Trade[];
  next_before_id: Int | null;
}
export interface Analytics {
  vwap_ticks: string | null;
  window_fills: number;
  band_volume: Int;
  as_of: string | null;
}
export interface HealthResponse {
  status: 'ok' | 'unhealthy';
  dependencies: Record<string, 'up' | 'down'>;
  trading_ready: boolean;
}
export interface Cycle {
  trader_ids: string[];
  edge_counts: Int[];
}
export interface Cycles {
  candidates: Cycle[];
}
export type Features = [number, number, number, number, number, number];
export interface RegimeMatch {
  id: Int;
  instrument_id: number;
  captured_at: string;
  features: Features;
  cosine_distance: number;
}
export interface Similar {
  matches: RegimeMatch[];
}
export interface Disclosure {
  id: Int;
  instrument_id: number | null;
  title: string;
  published_at: string;
  rank: number;
}
export interface Search {
  items: Disclosure[];
}
export interface PlanNode {
  'Node Type': string;
  'Relation Name'?: string;
  'Index Name'?: string;
  'Startup Cost'?: number;
  'Total Cost'?: number;
  'Actual Rows'?: Int;
  'Shared Hit Blocks'?: Int;
  'Shared Read Blocks'?: Int;
  Filter?: string;
  'Index Cond'?: string;
  'Recheck Cond'?: string;
  Plans?: PlanNode[];
}
export interface ExplainPlan {
  Plan: PlanNode;
  'Execution Time'?: number;
  'Planning Time'?: number;
  [key: string]: unknown;
}
export type Scenario = 'price_band' | 'recent_executions';
export interface Optimizer {
  scenario: Scenario;
  row_count: Int;
  dataset_size: Int;
  plans: { forced_sequential: ExplainPlan; automatic: ExplainPlan };
}
export interface Desk {
  desk_id: number;
  realized_pnl: Int;
  execution_volume: Int;
}
export interface Rollup {
  items: Desk[];
}
export type SimulatorState = 'RUNNING' | 'STOPPING' | 'STOPPED' | 'ERROR';
export interface SimulationStart {
  instrument_ids: number[];
  bot_count: number;
  orders_per_second: number;
  volatility: 'low' | 'medium' | 'high';
  seed: Int;
  max_duration_seconds: number;
}
export interface SimulationStatus {
  run_id: string | null;
  state: SimulatorState;
  started_at: string | null;
  stopped_at: string | null;
  active_bots: number;
  instrument_ids: number[];
  config: SimulationStart | null;
  orders_attempted: Int;
  orders_accepted: Int;
  orders_rejected: Int;
  orders_cancelled: Int;
  backpressure_events: Int;
  active_bot_orders: Int;
  committed_executions: Int;
  last_action_at: string | null;
  last_error: string | null;
  derived_workers: Record<string, 'ready' | 'retrying' | 'initializing'>;
}
export type FixtureState =
  'populated' | 'empty' | 'loading' | 'stale' | 'error' | 'large' | 'no-instruments';
export type Outcome = 'accepted' | 'partial' | 'filled' | 'rejected' | 'unknown';
export interface PreviewSession {
  role: AccountRole;
  expiresAt: number;
  kind: 'mock-preview';
}
