import { requirePageRole } from '@/lib/server/session';
import { AppShell } from '@/components/app-shell';
import { RoleGuard } from '@/components/preview-provider';
export default async function TraderLayout({ children }: { children: React.ReactNode }) {
  await requirePageRole('TRADER');
  return (
    <RoleGuard role="TRADER">
      <AppShell role="TRADER">{children}</AppShell>
    </RoleGuard>
  );
}
