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
      className="flex flex-col items-center gap-4 border-r border-[color:var(--line)] bg-[linear-gradient(180deg,rgba(248,250,252,0.94)_0%,rgba(239,244,255,0.9)_100%)] px-2 py-3"
      aria-label="App switcher"
    >
      <div
        className="grid h-10 w-10 place-items-center rounded-[16px] border border-white/70 bg-[linear-gradient(135deg,#2563eb_0%,#1d4ed8_52%,#1e40af_100%)] text-[0.72rem] font-bold tracking-[0.08em] text-white shadow-[0_18px_30px_rgba(37,99,235,0.32)]"
        title="InboxOS"
      >
        IO
      </div>
      <nav className="grid gap-2">
        {items.map((item) => {
          const active =
            pathname === item.href || pathname.startsWith(`${item.href}/`);
          return (
            <Link
              key={item.href}
              href={item.href}
              className={[
                "group grid h-12 w-12 place-items-center rounded-[16px] border text-[color:var(--text-muted)] shadow-[inset_0_1px_0_rgba(255,255,255,0.7)] transition-[transform,background-color,border-color,color,box-shadow] duration-150 ease-[var(--ease-out)] active:scale-[0.97]",
                active
                  ? "border-[color:var(--line-emphasis)] bg-white text-[color:var(--accent-strong)] shadow-[0_18px_28px_rgba(15,23,42,0.12)]"
                  : "border-transparent bg-white/45 hover:border-[color:var(--line-strong)] hover:bg-white hover:text-[color:var(--text)] hover:shadow-[0_12px_24px_rgba(15,23,42,0.08)]",
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
