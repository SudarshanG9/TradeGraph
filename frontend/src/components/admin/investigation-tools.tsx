import Link from 'next/link';
import {Activity,Database,GitFork,Network,Search} from 'lucide-react';
export function InvestigationTools(){return <section><h2 className="tools-heading">Investigation tools</h2><div className="grid-3">{[
 {title:'Market Surveillance',slug:'surveillance',description:'Investigate counterparty trading cycles in Neo4j.',Icon:Network},
 {title:'Market Regime Explorer',slug:'regimes',description:'Find similar historical conditions with pgvector.',Icon:Activity},
 {title:'Disclosure Search',slug:'disclosures',description:'Full-text search across market disclosures.',Icon:Search},
 {title:'SQL Optimizer',slug:'optimizer',description:'Compare PostgreSQL execution plans side by side.',Icon:Database},
 {title:'Desk Analytics',slug:'desks',description:'Recursive desk PnL and volume rollups.',Icon:GitFork},
].map(({title,slug,description,Icon})=><Link className="card tool-card" href={`/admin/${slug}`} key={slug}><Icon size={20}/><h3>{title}</h3><p className="caption">{description}</p></Link>)}</div></section>;}
