'use client';
import { useRouter } from 'next/navigation';
import { usePreview } from './preview-provider';
import { Button, Notice } from './ui';
export function ServiceUnavailable({
  retry,
  session = false,
}: {
  retry?: () => void;
  session?: boolean;
}) {
  const router = useRouter();
  const { retrySession } = usePreview();
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
          if (session) retrySession();
          router.refresh();
          retry?.();
        }}
      >
        Retry
      </Button>
    </div>
  );
}
