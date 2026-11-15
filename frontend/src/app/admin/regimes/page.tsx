'use client';
import {useState} from 'react';
import type {Similar} from '@/lib/contracts';
import {usePreview} from '@/components/preview-provider';
import {Heading,Skeleton} from '@/components/ui';
import {RegimeSearch} from '@/components/admin/regime-search';
import {RegimeResults} from '@/components/admin/regime-results';
export default function Regimes(){const {fixture}=usePreview();const [results,setResults]=useState<Similar|null>(null),[busy,setBusy]=useState(false);return <><Heading title="Market Regime Explorer" description="Vector similarity retrieval over six engineered market features, via pgvector + HNSW."/><div className="stack"><RegimeSearch onResult={setResults} onBusy={setBusy}/>{busy||fixture==='loading'?<Skeleton/>:<RegimeResults results={results}/>}</div></>;}
