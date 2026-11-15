import {AppShell} from '@/components/app-shell';
import {RoleGuard} from '@/components/preview-provider';
export default function AdminLayout({children}:{children:React.ReactNode}){return <RoleGuard role="COMPLIANCE_ADMIN"><AppShell role="COMPLIANCE_ADMIN">{children}</AppShell></RoleGuard>;}
