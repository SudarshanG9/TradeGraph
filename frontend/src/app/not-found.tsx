import Link from 'next/link';
export default function NotFound() {
  return (
    <main className="loading-route stack">
      <h1>Page not found</h1>
      <p>This route is not part of the TradeGraph preview.</p>
      <Link className="link" href="/auth">
        Return to authentication →
      </Link>
    </main>
  );
}
