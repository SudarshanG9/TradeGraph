import type * as C from './contracts';
import { assertRole, integer, MAX_INT, validateOrder } from './exact';
import * as F from './mock/fixtures';
export interface PageQuery { limit?: number; before_id?: C.Int }
export type RegimeQuery = { instrument_id:number; k:number } & ({current:true;features?:never}|{features:C.Features;current?:never});
export interface Services {
 auth: { preview(role:C.AccountRole): C.PreviewSession; login(request:C.LoginRequest, selected:C.AccountRole): Promise<C.PreviewSession> };
 instruments: { list(): Promise<C.InstrumentCatalog> };
 account: { get(): Promise<C.Account> };
 orders: { list(query?:PageQuery):Promise<C.OwnOrders>; submit(order:C.NewOrder):Promise<C.AcceptedOrder>; cancel(id:C.Int):Promise<C.CancelledOrder> };
 market: { book(symbol:string):Promise<C.Book>; trades(symbol:string,query?:PageQuery):Promise<C.Trades>; analytics(symbol:string,lower:C.Int,upper:C.Int):Promise<C.Analytics> };
 health: { get():Promise<C.HealthResponse> };
 surveillance: { cycles(limit:number):Promise<C.Cycles> };
 regimes: { similar(query:RegimeQuery):Promise<C.Similar> };
 disclosures: { search(q:string,limit?:number):Promise<C.Search> };
 optimizer: { compare(scenario:C.Scenario,instrument_id:number,lower:C.Int,upper:C.Int):Promise<C.Optimizer> };
 desks: { rollup():Promise<C.Rollup> };
 simulator: { status():Promise<C.SimulationStatus>; start(config:C.SimulationStart):Promise<C.SimulationStatus>; stop():Promise<C.SimulationStatus> };
}
const wait = () => new Promise<void>(resolve=>setTimeout(resolve,220));
const copy = <T,>(value:T):T=>structuredClone(value);
export function createMockServices(session:()=>C.PreviewSession|null, fixture:()=>C.FixtureState, outcome:()=>C.Outcome): Services {
 let localOrders = copy(F.orders), sim = copy(F.stopped), nextId = 9000n;
 const guard = async (role?:C.AccountRole) => {
  if (role) assertRole(session(),role); else { const s=session(); if(!s) throw new Error('SESSION_EXPIRED'); assertRole(s,s.role); }
  await wait();
  if(fixture()==='error') throw new Error('Demo service unavailable. Switch the fixture to Populated and retry.');
 };
 const instrument = (symbol:string) => { const item=F.catalog.items.find(i=>i.symbol===symbol); if(!item) throw new Error('INSTRUMENT_NOT_FOUND'); return item; };
 const page = <T extends {id:C.Int}>(items:T[],q:PageQuery={}) => {
  const limit=q.limit??5; if(limit<1||limit>100) throw new Error('Invalid limit');
  const filtered=items.filter(x=>BigInt(x.id)<BigInt(q.before_id??String(MAX_INT))).sort((a,b)=>BigInt(a.id)>BigInt(b.id)?-1:1);
  const result=filtered.slice(0,limit); return {items:copy(result),next_before_id:result.length===limit?result.at(-1)!.id:null};
 };
 const empty=()=>fixture()==='empty';
 const tradesFor=(symbol:string)=>empty()?[]:F.executions.filter(t=>t.instrument_id===instrument(symbol).id);
 return {
  auth:{preview:role=>({role,expiresAt:Date.now()+900000,kind:'mock-preview'}),login:async(request,selected)=>{
   await wait(); const role=request.email==='admin@tradegraph.sim'?'COMPLIANCE_ADMIN':request.email==='alice@tradegraph.sim'?'TRADER':null;
   if(!role||request.password!=='preview-only') throw new Error('Invalid demo credentials. Use the preview identity below.');
   if(role!==selected) throw new Error('Role mismatch. The demo identity does not match the selected role.');
   return {role,expiresAt:Date.now()+900000,kind:'mock-preview'};
  }},
  instruments:{list:async()=>{await guard();return copy(F.catalog);}},
  account:{get:async()=>{await guard('TRADER');return copy(fixture()==='large'?F.largeAccount:empty()?{...F.account,cash_balance:'0',escrow_balance:'0',positions:[]}:F.account);}},
  orders:{list:async(q)=>{await guard('TRADER'); return page(empty()?[]:fixture()==='large'?[{...localOrders[0],id:'9007199254740993'}]:localOrders,q);},submit:async(order)=>{
   await guard('TRADER');validateOrder(order,instrument(F.catalog.items.find(i=>i.id===order.instrument_id)?.symbol??''));
   if(outcome()==='rejected') throw new Error('Mock order rejected: insufficient collateral. No order was placed.');
   if(outcome()==='unknown') throw new Error('Unknown mock outcome. Reconcile order history before retrying; acceptance is not settlement.');
   const id=String(++nextId) as C.Int, quantity=BigInt(order.quantity), lot=BigInt(F.catalog.items.find(i=>i.id===order.instrument_id)!.lot_size);
   const filled=outcome()==='filled'?quantity:outcome()==='partial'&&quantity>lot?lot:0n;
   localOrders.unshift({...order,id,trader_id:F.trader,filled_quantity:String(filled) as C.Int,status:filled===quantity?'FILLED':filled>0n?'PARTIAL':'OPEN',created_at:F.asOf,updated_at:F.asOf,archived:false});
   return {order_id:id,status:'OPEN',accepted_at:F.asOf};
  },cancel:async(id)=>{await guard('TRADER');if(outcome()==='unknown') throw new Error('Unknown cancellation outcome. Reconcile before retrying.');const row=localOrders.find(o=>o.id===id);if(!row) throw new Error('ORDER_NOT_FOUND');if(!['OPEN','PARTIAL'].includes(row.status)) throw new Error('ORDER_TERMINAL');const remaining=String(BigInt(row.quantity)-BigInt(row.filled_quantity)) as C.Int;row.status='CANCELLED';return {order_id:id,status:'CANCELLED',cancelled_quantity:remaining};}},
  market:{book:async(symbol)=>{await guard(); const b=F.depth(instrument(symbol).id);return empty()?{...b,bids:[],asks:[],as_of:null}: {...b,stale:fixture()==='stale'};},trades:async(symbol,q)=>{await guard();return page(tradesFor(symbol),q);},analytics:async(symbol,lower,upper)=>{
   await guard(); const l=integer(lower,0n),u=integer(upper,0n);if(l>u) throw new Error('Lower bound must not exceed upper bound.');
   const rows=tradesFor(symbol),window=rows.slice(0,100),qty=window.reduce((s,t)=>s+BigInt(t.quantity),0n),notional=window.reduce((s,t)=>s+BigInt(t.quantity)*BigInt(t.price_ticks),0n);
   const scaled=qty?notional*10000n/qty:0n;
   return {vwap_ticks:qty?`${scaled/10000n}.${String(scaled%10000n).padStart(4,'0')}`:null,window_fills:window.length,band_volume:String(rows.filter(t=>BigInt(t.price_ticks)>=l&&BigInt(t.price_ticks)<=u).reduce((s,t)=>s+BigInt(t.quantity),0n)) as C.Int,as_of:rows[0]?.executed_at??null};
  }},
  health:{get:async()=>{await guard('COMPLIANCE_ADMIN');return copy(F.health);}},
  surveillance:{cycles:async(limit)=>{await guard('COMPLIANCE_ADMIN');if(!Number.isInteger(limit)||limit<1||limit>100) throw new Error('Limit must be 1–100.');return {candidates:empty()?[]:copy(F.cycles.candidates.slice(0,limit))};}},
  regimes:{similar:async(q)=>{await guard('COMPLIANCE_ADMIN');if(empty()) {if(q.current) throw new Error('NO_MARKET_OBSERVATIONS');return {matches:[]};}if(q.features&&(!q.features.every(Number.isFinite)||!q.features.some(x=>x!==0))) throw new Error('Enter six finite values, at least one nonzero.');if(q.current&&q.features) throw new Error('Select exactly one feature mode.');if(q.instrument_id!==1)return {matches:[]};const matches=copy(F.similar.matches);if(q.features)for(const row of matches){const dot=row.features.reduce((s,x,i)=>s+x*q.features![i],0),den=Math.hypot(...row.features)*Math.hypot(...q.features);row.cosine_distance=1-dot/den;}return {matches:matches.sort((a,b)=>a.cosine_distance-b.cosine_distance).slice(0,q.k)};}},
  disclosures:{search:async(q,limit=20)=>{await guard('COMPLIANCE_ADMIN');if(!q.trim()||q.length>500)throw new Error('Enter a query from 1 to 500 characters.');const terms=q.toLowerCase().trim().split(/\s+/);return {items:empty()?[]:copy(F.disclosures.filter(d=>terms.some(t=>d.title.toLowerCase().includes(t))).slice(0,limit))};}},
  optimizer:{compare:async(scenario,id,lower,upper)=>{await guard('COMPLIANCE_ADMIN');if(scenario==='price_band'){if(!F.catalog.items.some(i=>i.id===id))throw new Error('Select a valid instrument.');if(integer(lower)>integer(upper))throw new Error('Lower bound must not exceed upper bound.');}const r=copy(F.optimizer);r.scenario=scenario;if(empty()) {r.dataset_size='0';for(const p of Object.values(r.plans)){p['Execution Time']=0.01;p.Plan.Plans=[{'Node Type':'Seq Scan','Relation Name':'execution','Actual Rows':'0'}];}}else if(scenario==='recent_executions'){for(const p of Object.values(r.plans)){p.Plan.Plans=[{'Node Type':'Seq Scan','Relation Name':'execution',Filter:"executed_at >= now() - interval '10 minutes'",'Actual Rows':'18'}];p['Execution Time']=0.04;}}else for(const p of Object.values(r.plans))if(p.Plan.Plans?.[0]){p.Plan.Plans[0].Filter=`instrument_id = ${id} AND price_ticks BETWEEN ${lower} AND ${upper}`;}return r;}},
  desks:{rollup:async()=>{await guard('COMPLIANCE_ADMIN');return empty()?{items:[]}:copy(F.rollup);}},
  simulator:{status:async()=>{await guard('COMPLIANCE_ADMIN');return copy(sim);},start:async(config)=>{
   await guard('COMPLIANCE_ADMIN');if(sim.state!=='STOPPED')throw new Error('Session conflict. No automatic recovery is available.');
   if(config.instrument_ids.length<1||config.instrument_ids.length>3||new Set(config.instrument_ids).size!==config.instrument_ids.length||config.instrument_ids.some(id=>!F.catalog.items.some(i=>i.id===id)))throw new Error('Select 1–3 distinct active instruments.');
   for(const [value,min,max]of [[config.bot_count,4,8],[config.orders_per_second,1,5],[config.max_duration_seconds,30,600]])if(!Number.isInteger(value)||value<min||value>max)throw new Error('Configuration is outside supported bounds.');integer(config.seed,0n);if(!['low','medium','high'].includes(config.volatility))throw new Error('Invalid volatility.');
   sim={...copy(F.stopped),run_id:'00000000-0000-4000-8000-000000000001',state:'RUNNING',started_at:F.asOf,active_bots:config.bot_count,instrument_ids:config.instrument_ids,config};return copy(sim);
  },stop:async()=>{await guard('COMPLIANCE_ADMIN');if(sim.state==='ERROR')throw new Error('Reconciliation required. No automatic restart.');sim={...sim,state:'STOPPING',active_bots:0};await wait();if(outcome()==='unknown'){sim={...sim,state:'ERROR',last_error:'STOP_FAILED_RECONCILIATION_REQUIRED'};}else sim={...sim,state:'STOPPED',stopped_at:F.asOf,active_bot_orders:'0'};return copy(sim);}}
 };
}
export const futureRefresh = { book:1500,trades:1500,orders:2000,account:5000,simulator:2500,surveillance:null,regimes:null,optimizer:null } as const;
