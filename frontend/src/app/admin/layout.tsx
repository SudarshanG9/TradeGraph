import { ServiceUnavailable } from '@/components/service-unavailable';
import { requirePageRole, sessionUnavailable } from '@/lib/server/session';
import { AppShell } from '@/components/app-shell';
import { RoleGuard } from '@/components/preview-provider';
export default async function AdminLayout({ children }: { children: React.ReactNode }) {
  try {
    await requirePageRole('COMPLIANCE_ADMIN');
  } catch (error) {
    if (sessionUnavailable(error)) return <ServiceUnavailable session />;
    throw error;
  }
  return (
    <RoleGuard role="COMPLIANCE_ADMIN">
      <AppShell role="COMPLIANCE_ADMIN">{children}</AppShell>
    </RoleGuard>
  );
}
