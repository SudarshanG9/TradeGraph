import { mockEnabled } from '@/lib/server/session';
import type { Metadata } from 'next';
import { PreviewProvider } from '@/components/preview-provider';
import './globals.css';
export const metadata: Metadata = {
  title: 'TradeGraph · Exchange & Surveillance Simulator',
  description:
    'Frontend demonstration of a synthetic financial exchange and database surveillance system. Authenticated synthetic trading and surveillance.',
};
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <PreviewProvider mock={mockEnabled()}>{children}</PreviewProvider>
      </body>
    </html>
  );
}
