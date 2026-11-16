'use client';
import { useRouter } from 'next/navigation';
import { Button, Notice } from './ui';
export function ServiceUnavailable({
  retry,
  session = false,
}: {
  retry?: () => void;
  session?: boolean;
}) {
  const router = useRouter();
  return (
    <div className="loading-route">
      <Notice tone="warning">
        {session
          ? 'Session service unavailable. Your login could not be verified.'
          : 'Page data temporarily unavailable.'}{' '}
        Try again after the service recovers.
      </Notice>
      <Button
        onClick={() => {
          router.refresh();
          retry?.();
        }}
      >
        Retry
      </Button>
    </div>
  );
}
