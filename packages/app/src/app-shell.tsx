"use client";

import { usePathname } from "next/navigation";

import { AppRail } from "@inboxos/ui/app-rail";

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const showRail = !pathname.startsWith("/auth");

  if (!showRail) {
    return <div className="page-shell auth-shell">{children}</div>;
  }

  return (
    <div className="app-root">
      <AppRail />
      <div className="page-shell">{children}</div>
    </div>
  );
}
