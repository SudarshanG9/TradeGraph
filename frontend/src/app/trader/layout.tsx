import {AppShell} from '@/components/app-shell';
import {RoleGuard} from '@/components/preview-provider';
export default function TraderLayout({children}:{children:React.ReactNode}){return <RoleGuard role="TRADER"><AppShell role="TRADER">{children}</AppShell></RoleGuard>;}
