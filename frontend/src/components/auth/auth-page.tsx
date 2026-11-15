'use client';
import {useEffect,useState} from 'react';
import {useRouter} from 'next/navigation';
import type {AccountRole,PreviewSession} from '@/lib/contracts';
import {homeFor} from '@/lib/exact';
import {usePreview} from '../preview-provider';
import {Notice} from '../ui';
import {AuthContainer} from './auth-container';
import {ModeSelector,RoleSelector,type AuthMode} from './auth-selectors';
import {SignInForm,SignUpForm} from './auth-form';
export function AuthPage(){const [mode,setMode]=useState<AuthMode>('signin'),[role,setRole]=useState<AccountRole>('TRADER'),[expired,setExpired]=useState(false);const {api,signIn}=usePreview(),router=useRouter();useEffect(()=>{setExpired(new URLSearchParams(window.location.search).get('reason')==='expired');},[]);const enter=(s:PreviewSession)=>{signIn(s);router.push(homeFor(s.role));};return <AuthContainer title={mode==='signin'?'Sign in':'Sign up'} footer={<div className="auth-footer"><p className="eyebrow">Mock role preview — for review only</p><div className="toolbar"><button className="link positive" onClick={()=>enter(api.auth.preview('TRADER'))}>View as Trader →</button><button className="link" onClick={()=>enter(api.auth.preview('COMPLIANCE_ADMIN'))}>View as Compliance Admin →</button></div></div>}><ModeSelector value={mode} onChange={setMode}/><RoleSelector value={role} onChange={setRole}/>{expired&&<div className="auth-feedback"><Notice tone="warning">Preview session expired. Open a new mock session to continue.</Notice></div>}{mode==='signin'?<SignInForm key={role} role={role} onSession={enter}/>:<SignUpForm key={role} role={role} onReturn={()=>setMode('signin')}/>}</AuthContainer>;}
