'use client';
import type { ReactNode } from 'react';
import { Brand } from '../app-shell';
import { Info } from 'lucide-react';
export function AuthContainer({
  title,
  children,
  footer,
}: {
  title: string;
  children: ReactNode;
  footer: ReactNode;
}) {
  return (
    <main className="auth-page">
      <div className="auth-wrap">
        <div className="auth-brand">
          <Brand />
        </div>
        <section className="auth-card card">
          <h1>{title}</h1>
          <p className="auth-subtitle">Access the exchange and surveillance simulator</p>
          {children}
          <div className="auth-notice">
            <Info size={14} />
            <p>
              Academic trading simulator built on synthetic funds and instruments — no real
              securities or money are involved. This is a local frontend preview.
            </p>
          </div>
        </section>
        {footer}
      </div>
    </main>
  );
}
