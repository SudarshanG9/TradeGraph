'use client';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { useState, type ReactNode } from 'react';
import {
  Activity,
  ArrowLeftRight,
  BarChart3,
  BriefcaseBusiness,
  Database,
  FileText,
  GitFork,
  LayoutDashboard,
  LogOut,
  Menu,
  Network,
  Search,
  Shield,
  User,
  X,
} from 'lucide-react';
import type { AccountRole, FixtureState, Outcome } from '@/lib/contracts';
import { usePreview } from './preview-provider';
import { Badge } from './ui';
const traderNav = [
  ['Dashboard', 'dashboard', LayoutDashboard],
  ['Trading Terminal', 'terminal', ArrowLeftRight],
  ['My Orders', 'orders', FileText],
  ['Market Analytics', 'analytics', BarChart3],
  ['Positions', 'account', BriefcaseBusiness],
] as const;
const adminNav = [
  ['Overview', 'overview', LayoutDashboard],
  ['Surveillance', 'surveillance', Network],
  ['Regime Explorer', 'regimes', Activity],
  ['Disclosures', 'disclosures', Search],
  ['SQL Optimizer', 'optimizer', Database],
  ['Desk Analytics', 'desks', GitFork],
] as const;
export function Brand() {
  return (
    <span className="brand">
      <span className="brand-icon">
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d="M5 18 11 6l8 7" fill="none" stroke="currentColor" strokeWidth="2.3" />
          <circle cx="5" cy="18" r="2.4" />
          <circle cx="11" cy="6" r="2.4" />
          <circle cx="19" cy="13" r="2.4" />
        </svg>
      </span>
      <strong>TradeGraph</strong>
    </span>
  );
}
export function AppShell({ role, children }: { role: AccountRole; children: ReactNode }) {
  const pathname = usePathname(),
    router = useRouter();
  const { logout, fixture, setFixture, outcome, setOutcome } = usePreview();
  const [open, setOpen] = useState(false);
  const isTrader = role === 'TRADER',
    nav = isTrader ? traderNav : adminNav,
    base = isTrader ? '/trader/' : '/admin/';
  const title = nav.find(([, slug]) => pathname === base + slug)?.[0] ?? 'Workspace';
  return (
    <div className={`app-shell ${isTrader ? 'trader' : 'admin'}`}>
      <a className="skip-link" href="#content">
        Skip to content
      </a>
      <header className="topbar">
        <button
          className="menu-toggle"
          aria-label={open ? 'Close navigation' : 'Open navigation'}
          aria-expanded={open}
          onClick={() => setOpen(!open)}
        >
          {open ? <X size={20} /> : <Menu size={20} />}
        </button>
        <Link href={base + (isTrader ? 'dashboard' : 'overview')}>
          <Brand />
        </Link>
        <span className="topbar-title">{title}</span>
        <div className="topbar-right">
          <span className="preview-status">
            <i />
            Mock preview
          </span>
          <Badge tone={isTrader ? 'green' : 'blue'}>
            {isTrader ? <User size={12} /> : <Shield size={12} />}{' '}
            {isTrader ? 'Trader' : 'Compliance Admin'}
          </Badge>
          <span className="avatar" title="Mock identity">
            {isTrader ? 'AC' : 'CA'}
          </span>
        </div>
      </header>
      <aside className={`sidebar ${open ? 'open' : ''}`} aria-label="Main navigation">
        <nav>
          {nav.map(([label, slug, Icon]) => (
            <Link
              key={slug}
              href={base + slug}
              aria-current={pathname === base + slug ? 'page' : undefined}
              onClick={() => setOpen(false)}
            >
              <Icon size={16} />
              {label}
            </Link>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <details className="preview-tools">
            <summary>Preview scenarios</summary>
            <label className="field">
              Data fixture
              <select value={fixture} onChange={(e) => setFixture(e.target.value as FixtureState)}>
                {(['populated', 'empty', 'loading', 'stale', 'error', 'large'] as const).map(
                  (x) => (
                    <option key={x} value={x}>
                      {x[0].toUpperCase() + x.slice(1)}
                    </option>
                  ),
                )}
              </select>
            </label>
            <label className="field">
              Action outcome
              <select value={outcome} onChange={(e) => setOutcome(e.target.value as Outcome)}>
                {(['accepted', 'partial', 'filled', 'rejected', 'unknown'] as const).map((x) => (
                  <option key={x} value={x}>
                    {x}
                  </option>
                ))}
              </select>
            </label>
            <button
              onClick={() => {
                logout();
                router.replace('/auth?reason=expired');
              }}
            >
              Preview expired session
            </button>
          </details>
          <button
            className="logout"
            onClick={() => {
              logout();
              router.replace('/auth');
            }}
          >
            <LogOut size={15} />
            Log out
          </button>
        </div>
      </aside>
      {open && (
        <button
          aria-label="Close navigation overlay"
          className="nav-backdrop"
          onClick={() => setOpen(false)}
        />
      )}
      <main id="content" className="main-content">
        {children}
      </main>
      <footer className="footer">
        TradeGraph is an academic trading simulation — synthetic funds and instruments only. No real
        securities are traded. <span>Demo data · UTC times</span>
      </footer>
    </div>
  );
}
