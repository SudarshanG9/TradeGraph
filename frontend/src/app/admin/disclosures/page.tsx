'use client';
import { useState } from 'react';
import type { Search } from '@/lib/contracts';
import { usePreview } from '@/components/preview-provider';
import { Heading, Skeleton } from '@/components/ui';
import { DisclosureSearch } from '@/components/admin/disclosure-search';
import { DisclosureResults } from '@/components/admin/disclosure-results';
export default function Disclosures() {
  const { fixture } = usePreview();
  const [results, setResults] = useState<Search | null>(null),
    [busy, setBusy] = useState(false);
  return (
    <>
      <Heading
        title="Market Disclosure Search"
        description="Full-text search over disclosure filings — PostgreSQL tsvector, GIN index, ts_rank."
      />
      <div className="stack">
        <DisclosureSearch onResult={setResults} onBusy={setBusy} />
        {busy || fixture === 'loading' ? <Skeleton /> : <DisclosureResults results={results} />}
      </div>
    </>
  );
}
