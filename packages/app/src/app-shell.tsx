import { AppRail } from "@inboxos/ui/app-rail";

export function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="app-root">
      <AppRail />
      <div className="page-shell">{children}</div>
    </div>
  );
}
