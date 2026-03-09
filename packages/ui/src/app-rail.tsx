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
    <aside
      className="flex flex-col items-center gap-2 border-r border-[var(--line)] bg-[#f1f3f7] px-1 py-[7px]"
      aria-label="App switcher"
    >
      <div
        className="grid h-7 w-7 place-items-center rounded-[8px] bg-[#1d4ed8] text-[0.62rem] font-bold text-white"
        title="InboxOS"
      >
        IO
      </div>
      <nav className="grid gap-1.5">
        {items.map((item) => {
          const active =
            pathname === item.href || pathname.startsWith(`${item.href}/`);
          return (
            <Link
              key={item.href}
              href={item.href}
              className={[
                "grid h-7 w-7 place-items-center rounded-[8px] border border-transparent text-[#475569] transition-colors",
                active
                  ? "border-[#d7deea] bg-white text-[#111827]"
                  : "hover:border-[#d7deea] hover:bg-white hover:text-[#111827]",
              ].join(" ")}
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
