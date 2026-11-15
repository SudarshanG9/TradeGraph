'use client';
import { Button, Notice } from '@/components/ui';
export default function ErrorBoundary({
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <main className="loading-route stack">
      <h1>Unable to display this preview</h1>
      <Notice tone="error">
        The frontend encountered an unexpected error. Retry to reload this view.
      </Notice>
      <div>
        <Button onClick={reset}>Retry view</Button>
      </div>
    </main>
  );
}
