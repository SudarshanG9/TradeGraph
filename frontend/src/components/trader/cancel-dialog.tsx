'use client';
import {useState} from 'react';
import type {OrderSummary} from '@/lib/contracts';
import {fmt} from '@/lib/exact';
import {usePreview} from '../preview-provider';
import {Button,Modal,Notice} from '../ui';
export function CancelDialog({order,onClose,onDone}:{order:OrderSummary;onClose:()=>void;onDone:()=>void}){const {api}=usePreview(),[busy,setBusy]=useState(false),[error,setError]=useState('');return <Modal title={`Cancel demo order #${order.id}?`} onClose={()=>{if(!busy)onClose();}}><p>Preview cancellation of the remaining {fmt(BigInt(order.quantity)-BigInt(order.filled_quantity))} units. No backend order or balance will change.</p>{error&&<Notice tone="error">{error}</Notice>}<div className="toolbar" style={{justifyContent:'flex-end',marginTop:16}}><Button onClick={onClose} disabled={busy}>Keep order</Button><Button variant="sell" disabled={busy} onClick={async()=>{setBusy(true);try{await api.orders.cancel(order.id);onDone();}catch(e){setError((e as Error).message);}finally{setBusy(false);}}}>{busy?'Cancellation pending…':'Confirm demo cancellation'}</Button></div></Modal>;}
