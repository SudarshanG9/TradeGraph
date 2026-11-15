'use client';
import {useEffect,useState} from 'react';
import {Search as SearchIcon} from 'lucide-react';
import type {Search} from '@/lib/contracts';
import {usePreview} from '../preview-provider';
import {Button,Notice} from '../ui';
export function DisclosureSearch({onResult,onBusy}:{onResult:(r:Search|null)=>void;onBusy:(v:boolean)=>void}){const {api,fixture}=usePreview();const [query,setQuery]=useState('market volatility'),[error,setError]=useState(''),[busy,setBusy]=useState(false);useEffect(()=>{onResult(null);setError('');},[fixture]);return <form className="stack" onSubmit={async e=>{e.preventDefault();setError('');setBusy(true);onBusy(true);try{onResult(await api.disclosures.search(query));}catch(e){setError((e as Error).message);onResult(null);}finally{setBusy(false);onBusy(false);}}}><div className="search-toolbar"><label className="search-input"><SearchIcon size={16}/><span className="sr-only">Disclosure search query</span><input aria-label="Disclosure search query" value={query} onChange={e=>setQuery(e.target.value)} maxLength={500} placeholder="Search disclosure titles…"/></label><Button variant="primary" disabled={busy||fixture==='loading'} type="submit">{busy?'Searching…':'Search'}</Button></div>{error&&<Notice tone="error">{error}</Notice>}</form>;}
