'use client';
import { ServiceUnavailable } from '@/components/service-unavailable';
/** Parent boundary catches exceptions in trader/admin layouts as well as pages. */
export default function ErrorBoundary({ retry }: { error: unknown; retry: () => void }) {
  return <ServiceUnavailable retry={retry} />;
}
