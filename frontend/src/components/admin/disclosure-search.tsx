'use client';
import { useEffect, useRef, useState } from 'react';
import { Search as SearchIcon } from 'lucide-react';
import type { Search } from '@/lib/contracts';
import { usePreview } from '../preview-provider';
import { Button, Notice } from '../ui';
export function DisclosureSearch({
  onResult,
  onBusy,
}: {
  onResult: (r: Search | null) => void;
  onBusy: (v: boolean) => void;
}) {
  const { api, fixture } = usePreview();
  const [query, setQuery] = useState('market volatility'),
    [error, setError] = useState(''),
    [busy, setBusy] = useState(false);
  const requestSequence = useRef(0);
  useEffect(() => {
    requestSequence.current++;
    setBusy(false);
    onBusy(false);
    onResult(null);
    setError('');
  }, [fixture]);
  return (
    <form
      className="stack"
      onSubmit={async (e) => {
        e.preventDefault();
        const request = ++requestSequence.current;
        setError('');
        setBusy(true);
        onBusy(true);
        try {
          if (!query.trim() || query.length > 500)
            throw new Error('Enter a query from 1 to 500 characters.');
          const result = await api.disclosures.search(query);
          if (request === requestSequence.current) onResult(result);
        } catch (e) {
          if (request !== requestSequence.current) return;
          setError((e as Error).message);
          onResult(null);
        } finally {
          if (request === requestSequence.current) {
            setBusy(false);
            onBusy(false);
          }
        }
      }}
    >
      <div className="search-toolbar">
        <label className="search-input">
          <SearchIcon size={16} />
          <span className="sr-only">Disclosure search query</span>
          <input
            aria-label="Disclosure search query"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            maxLength={500}
            placeholder="Search disclosures…"
          />
        </label>
        <Button variant="primary" disabled={busy || fixture === 'loading'} type="submit">
          {busy ? 'Searching…' : 'Search'}
        </Button>
      </div>
      {error && (
        <Notice tone="error">
          {error}{' '}
          <button className="link" type="submit" disabled={busy}>
            Retry
          </button>
        </Notice>
      )}
    </form>
  );
}
