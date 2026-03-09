"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { CalendarDays, Check, Mail } from "lucide-react";

import { api } from "@inboxos/lib/api";
import { AuthSessionResponse } from "@inboxos/types";

const items = [
  { href: "/mail", label: "Mail", icon: Mail },
  { href: "/tasks", label: "Tasks", icon: Check },
  { href: "/calendar", label: "Calendar", icon: CalendarDays },
] as const;

export function AppRail() {
  const pathname = usePathname();
  const [session, setSession] = useState<AuthSessionResponse | null>(null);

  useEffect(() => {
    let cancelled = false;

    void api
      .getSession()
      .then((nextSession) => {
        if (!cancelled && nextSession.authenticated) {
          setSession(nextSession);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setSession(null);
        }
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const profileLabel =
    session?.account_name ??
    session?.user?.display_name ??
    session?.account_email ??
    session?.user?.primary_email ??
    "Settings";
  const initials = profileLabel
    .split(" ")
    .map((chunk) => chunk[0] ?? "")
    .join("")
    .slice(0, 2)
    .toUpperCase();

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
      <div className="rail-footer">
        <Link
          href="/settings"
          className={`rail-link rail-profile-link ${
            pathname === "/settings" || pathname.startsWith("/settings/")
              ? "active"
              : ""
          }`.trim()}
          title={profileLabel}
          aria-label="Settings"
        >
          {session?.account_picture ? (
            <img
              src={session.account_picture}
              alt=""
              className="rail-avatar-image"
            />
          ) : (
            <span className="rail-avatar-fallback">{initials || "IO"}</span>
          )}
        </Link>
      </div>
    </aside>
  );
}
