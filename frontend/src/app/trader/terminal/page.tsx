'use client';
import {InstrumentSelector,usePreview,useResource} from '@/components/preview-provider';
import {Badge,DataState,Notice,Refresh} from '@/components/ui';
import {OrderBook} from '@/components/trader/order-book';
import {PriceChart} from '@/components/trader/price-chart';
import {OrderForm} from '@/components/trader/order-form';
import {MarketMetrics} from '@/components/trader/market-metrics';
import {ExecutionsTable} from '@/components/trader/executions-table';
export default function Terminal(){const {api,instrument}=usePreview();const r=useResource(async()=>{const [book,trades,analytics]=await Promise.all([api.market.book(instrument.symbol),api.market.trades(instrument.symbol,{limit:100}),api.market.analytics(instrument.symbol,'95','105')]);return{book,trades,analytics};},[instrument.id]);return <><h1 className="sr-only">Trading Terminal</h1><div className="terminal-toolbar"><div className="toolbar"><InstrumentSelector/><Badge>Tick size {instrument.tick_size} minor / tick</Badge><Badge>Lot size {instrument.lot_size} units</Badge></div><div className="toolbar"><span className="caption">Mock market data</span><Refresh onClick={r.reload} loading={r.loading}/></div></div><DataState {...r} retry={r.reload}>{r.data&&<>{r.data.book.stale&&<div className="mb-4"><Notice tone="warning">Depth is stale. Derived quotes do not guarantee execution.</Notice></div>}<div className="terminal-grid"><OrderBook book={r.data.book}/><div className="stack terminal-center"><PriceChart trades={r.data.trades.items}/><MarketMetrics analytics={r.data.analytics}/><ExecutionsTable mode="terminal" trades={r.data.trades.items.slice(0,3)}/></div><OrderForm key={instrument.id}/></div></>}</DataState></>;}
