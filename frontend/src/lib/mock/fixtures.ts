import type {
  Account,
  Book,
  Cycles,
  Disclosure,
  Features,
  HealthResponse,
  InstrumentCatalog,
  Int,
  Optimizer,
  OrderSummary,
  Rollup,
  Similar,
  SimulationStatus,
  Trade,
} from '../contracts';
export const asOf = '2026-11-15T14:02:11Z';
export const trader = 'a1f20000-0000-4000-8000-000000009c3d';
export const traders = [
  trader,
  'b77e0000-0000-4000-8000-000000001120',
  '44aa0000-0000-4000-8000-00000000e09f',
  '2c0d0000-0000-4000-8000-0000000077af',
  '9b110000-0000-4000-8000-000000004e02',
];
export const catalog: InstrumentCatalog = {
  items: [
    { id: 1, symbol: 'ACME', tick_size: '1', lot_size: '1', is_active: true },
    { id: 2, symbol: 'BETA', tick_size: '5', lot_size: '10', is_active: true },
    { id: 3, symbol: 'GAMMA', tick_size: '10', lot_size: '5', is_active: true },
  ],
};
export const account: Account = {
  trader_id: trader,
  cash_balance: '8425000',
  escrow_balance: '340000',
  positions: [
    { instrument_id: 1, net_quantity: '40', realized_pnl: '62000', pnl_basis: 'gross' },
    { instrument_id: 2, net_quantity: '-20', realized_pnl: '-9500', pnl_basis: 'gross' },
  ],
};
export const largeAccount: Account = {
  ...account,
  cash_balance: '9007199254740993',
  escrow_balance: '340000',
  positions: [
    {
      instrument_id: 1,
      net_quantity: '9007199254740993',
      realized_pnl: '-9007199254740993',
      pnl_basis: 'gross',
    },
  ],
};
const order = (
  id: Int,
  instrument_id: number,
  side: 'BUY' | 'SELL',
  price_ticks: Int,
  quantity: Int,
  filled_quantity: Int,
  status: OrderSummary['status'],
  created_at: string,
  archived = false,
): OrderSummary => ({
  id,
  trader_id: trader,
  instrument_id,
  side,
  price_ticks,
  quantity,
  filled_quantity,
  status,
  created_at,
  updated_at: created_at,
  archived,
});
export const orders: OrderSummary[] = [
  order('8841', 1, 'BUY', '100', '10', '6', 'PARTIAL', asOf),
  order('8830', 2, 'SELL', '220', '30', '30', 'FILLED', '2026-11-15T11:47:03Z'),
  order('8812', 1, 'BUY', '98', '15', '0', 'OPEN', '2026-11-14T16:20:00Z'),
  order('8790', 1, 'SELL', '105', '8', '8', 'FILLED', '2026-11-14T10:05:00Z'),
  order('8764', 2, 'BUY', '210', '20', '10', 'CANCELLED', '2026-11-13T09:30:00Z', true),
  order('8750', 3, 'BUY', '305', '15', '0', 'OPEN', '2026-11-12T09:20:00Z'),
  order('8740', 1, 'SELL', '108', '20', '20', 'FILLED', '2026-11-11T12:10:00Z', true),
];
// Fixed, explicit observations. No random chart data or generated intermediate prices.
const observations: [string, Int, Int][] = [
  ['13:10:00', '97', '10'],
  ['13:13:00', '98', '8'],
  ['13:17:00', '98', '12'],
  ['13:21:00', '97', '6'],
  ['13:25:00', '99', '10'],
  ['13:28:00', '98', '7'],
  ['13:32:00', '100', '5'],
  ['13:35:00', '99', '9'],
  ['13:39:00', '100', '6'],
  ['13:42:00', '99', '11'],
  ['13:45:00', '101', '7'],
  ['13:49:00', '100', '13'],
  ['13:52:00', '102', '5'],
  ['13:55:00', '101', '9'],
  ['13:59:02', '99', '4'],
  ['14:01:48', '99', '12'],
  ['14:02:11', '100', '6'],
];
export const executions: Trade[] = observations
  .map<Trade>(([clock, price_ticks, quantity], i) => ({
    id: String(50215 + i) as Int,
    instrument_id: 1,
    buy_order_id: i === 16 ? '8841' : '8795',
    sell_order_id: '8790',
    buy_trader_id: trader,
    sell_trader_id: traders[1],
    price_ticks,
    quantity,
    executed_at: `2026-11-15T${clock}Z`,
  }))
  .reverse();
executions.push({
  ...executions[0],
  id: '50210',
  instrument_id: 2,
  price_ticks: '220',
  quantity: '30',
  executed_at: '2026-11-15T11:47:03Z',
  buy_order_id: '8805',
  sell_order_id: '8830',
});
export const depth = (id: number): Book => {
  const item = catalog.items.find((x) => x.id === id)!;
  const base = id === 1 ? 100n : id === 2 ? 220n : 305n;
  return {
    symbol: item.symbol,
    bids: [40, 65, 30, 52, 18].map((q, i) => ({
      price_ticks: String(base - BigInt(i)) as Int,
      quantity: String(q * Number(item.lot_size)) as Int,
    })),
    asks: [20, 55, 70, 41, 33].map((q, i) => ({
      price_ticks: String(base + 1n + BigInt(i)) as Int,
      quantity: String(q * Number(item.lot_size)) as Int,
    })),
    as_of: asOf,
    stale: false,
    epoch: 'mock',
    version: '14',
  };
};
export const health: HealthResponse = {
  status: 'ok',
  dependencies: { postgres: 'up', redis: 'up', neo4j: 'up', regimes: 'up' },
  trading_ready: true,
};
export const cycles: Cycles = {
  candidates: [
    { trader_ids: traders.slice(0, 3), edge_counts: ['7', '5', '6'] },
    {
      trader_ids: [traders[3], traders[4], traders[0], traders[1]],
      edge_counts: ['3', '2', '4', '2'],
    },
    { trader_ids: traders, edge_counts: ['1', '1', '2', '1', '1'] },
  ],
};
export const currentFeatures: Features = [0.12, 0.34, -0.08, 1.42, 0.91, 0.056];
export const similar: Similar = {
  matches: [
    {
      id: '11042',
      instrument_id: 1,
      captured_at: '2026-10-02T09:14:00Z',
      features: [0.11, 0.31, -0.07, 1.4, 0.9, 0.05],
      cosine_distance: 0.018,
    },
    {
      id: '10988',
      instrument_id: 1,
      captured_at: '2026-09-21T15:40:00Z',
      features: [0.13, 0.29, -0.06, 1.38, 0.86, 0.06],
      cosine_distance: 0.041,
    },
    {
      id: '10654',
      instrument_id: 1,
      captured_at: '2026-08-30T11:02:00Z',
      features: [0.1, 0.36, -0.09, 1.5, 0.94, 0.052],
      cosine_distance: 0.067,
    },
    {
      id: '10401',
      instrument_id: 1,
      captured_at: '2026-08-11T08:55:00Z',
      features: [0.15, 0.25, -0.04, 1.6, 0.82, 0.063],
      cosine_distance: 0.093,
    },
  ],
};
export const disclosures: Disclosure[] = [
  {
    id: '401',
    instrument_id: 1,
    title: 'Q3 Volatility Disclosure — ACME Instrument Desk',
    published_at: '2026-10-03T09:00:00Z',
    rank: 0.91,
  },
  {
    id: '398',
    instrument_id: 1,
    title: 'Market Risk Factors Update — Elevated Intraday Volatility',
    published_at: '2026-09-19T09:00:00Z',
    rank: 0.78,
  },
  {
    id: '387',
    instrument_id: 2,
    title: 'Liquidity and Volatility Notice — BETA Instrument',
    published_at: '2026-09-02T09:00:00Z',
    rank: 0.64,
  },
  {
    id: '370',
    instrument_id: null,
    title: 'Quarterly Market Structure Review',
    published_at: '2026-08-14T09:00:00Z',
    rank: 0.41,
  },
];
export const rollup: Rollup = {
  items: [
    { desk_id: 1, realized_pnl: '492000', execution_volume: '18240' },
    { desk_id: 2, realized_pnl: '311000', execution_volume: '12480' },
    { desk_id: 4, realized_pnl: '220500', execution_volume: '8910' },
    { desk_id: 5, realized_pnl: '90500', execution_volume: '3570' },
    { desk_id: 3, realized_pnl: '-19000', execution_volume: '5760' },
  ],
};
export const optimizer: Optimizer = {
  scenario: 'price_band',
  row_count: '1',
  dataset_size: '4200000',
  plans: {
    forced_sequential: {
      'Execution Time': 842.3,
      'Planning Time': 0.18,
      Plan: {
        'Node Type': 'Aggregate',
        'Actual Rows': '1',
        'Startup Cost': 98214,
        'Total Cost': 98214.1,
        'Shared Hit Blocks': '12000',
        'Shared Read Blocks': '3100',
        Plans: [
          {
            'Node Type': 'Seq Scan',
            'Relation Name': 'execution',
            Filter: 'instrument_id = 1 AND price_ticks BETWEEN 95 AND 105',
            'Actual Rows': '1240',
          },
        ],
      },
    },
    automatic: {
      'Execution Time': 6.1,
      'Planning Time': 0.24,
      Plan: {
        'Node Type': 'Aggregate',
        'Actual Rows': '1',
        'Startup Cost': 412.6,
        'Total Cost': 412.7,
        'Shared Hit Blocks': '60',
        'Shared Read Blocks': '14',
        Plans: [
          {
            'Node Type': 'Bitmap Heap Scan',
            'Relation Name': 'execution',
            'Recheck Cond': 'instrument_id = 1 AND price_ticks BETWEEN 95 AND 105',
            'Actual Rows': '1240',
            Plans: [
              {
                'Node Type': 'Bitmap Index Scan',
                'Index Name': 'idx_execution_price_ticks',
                'Index Cond': 'price_ticks BETWEEN 95 AND 105',
              },
            ],
          },
        ],
      },
    },
  },
};
export const stopped: SimulationStatus = {
  run_id: null,
  state: 'STOPPED',
  started_at: null,
  stopped_at: null,
  active_bots: 0,
  instrument_ids: [],
  config: null,
  orders_attempted: '0',
  orders_accepted: '0',
  orders_rejected: '0',
  orders_cancelled: '0',
  backpressure_events: '0',
  active_bot_orders: '0',
  committed_executions: '0',
  last_action_at: null,
  last_error: null,
  derived_workers: { redis: 'ready', neo4j: 'ready', regimes: 'ready' },
};
