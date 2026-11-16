import { requirePageRole } from '@/lib/server/session';
import { AppShell } from '@/components/app-shell';
import { RoleGuard } from '@/components/preview-provider';
export default async function AdminLayout({ children }: { children: React.ReactNode }) {
  await requirePageRole('COMPLIANCE_ADMIN');
  return (
    <RoleGuard role="COMPLIANCE_ADMIN">
      <AppShell role="COMPLIANCE_ADMIN">{children}</AppShell>
    </RoleGuard>
  );
}
