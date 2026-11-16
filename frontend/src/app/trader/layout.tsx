import { ServiceUnavailable } from '@/components/service-unavailable';
import { requirePageRole, sessionUnavailable } from '@/lib/server/session';
import { AppShell } from '@/components/app-shell';
import { RoleGuard } from '@/components/preview-provider';
export default async function TraderLayout({ children }: { children: React.ReactNode }) {
  try {
    await requirePageRole('TRADER');
  } catch (error) {
    if (sessionUnavailable(error)) return <ServiceUnavailable session />;
    throw error;
  }
  return (
    <RoleGuard role="TRADER">
      <AppShell role="TRADER">{children}</AppShell>
    </RoleGuard>
  );
}
