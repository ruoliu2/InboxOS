import type { Metadata } from "next";

import "./globals.css";
import { AppShell } from "@inboxos/app/app-shell";

export const metadata: Metadata = {
  title: "InboxOS - Mail Workspace",
  description: "Mail-inspired AI workspace shared across web and macOS",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body className="app-body">
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
