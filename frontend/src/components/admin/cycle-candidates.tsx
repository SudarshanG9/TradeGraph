'use client';
import type {Cycle} from '@/lib/contracts';
import {Card,Empty,Table} from '../ui';
import {shortId} from './cycle-graph';
export function CycleCandidates({candidates,selected,onSelect}:{candidates:Cycle[];selected:number;onSelect:(i:number)=>void}){return <Card title="Cycle candidates"><Table label="Cycle candidates" headers={['Candidate','Traders','Length','Relationship trades','']} >{candidates.map((c,i)=><tr key={c.trader_ids.join()} className={selected===i?'selected':''}><td className="mono">{i+1} <span className="caption">(local)</span></td><td className="mono wrap" title={c.trader_ids.join(' → ')}>{c.trader_ids.map(shortId).join(' → ')}</td><td>{c.trader_ids.length}</td><td className="mono">{c.edge_counts.join(' / ')}</td><td><button className="link" onClick={()=>onSelect(i)}>{selected===i?'Selected':'Investigate'}</button></td></tr>)}</Table>{!candidates.length&&<Empty message="No cycle candidates detected in this demo fixture."/>}</Card>;}
