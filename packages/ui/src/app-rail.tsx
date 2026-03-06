"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { CalendarDays, Check, Mail } from "lucide-react";

const items = [
  { href: "/mail", label: "Mail", icon: Mail },
  { href: "/tasks", label: "Tasks", icon: Check },
  { href: "/calendar", label: "Calendar", icon: CalendarDays },
] as const;

export function AppRail() {
  const pathname = usePathname();

  return (
    <aside className="app-rail" aria-label="App switcher">
      <div className="rail-brand" title="InboxOS">
        IO
      </div>
      <nav className="rail-nav">
        {items.map((item) => {
          const active =
            pathname === item.href || pathname.startsWith(`${item.href}/`);
          return (
            <Link
              key={item.href}
              href={item.href}
              className={`rail-link ${active ? "active" : ""}`.trim()}
              title={item.label}
              aria-label={item.label}
            >
              <item.icon size={16} strokeWidth={1.9} />
            </Link>
          );
        })}
      </nav>
    </aside>
  );
}
