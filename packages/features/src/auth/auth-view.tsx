"use client";

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { ArrowRight, CalendarDays, Mail } from "lucide-react";

import { api } from "@inboxos/lib/api";
import { AuthSessionResponse } from "@inboxos/types";
import { Button } from "@inboxos/ui/button";

export function AuthView() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [session, setSession] = useState<AuthSessionResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isConnecting, setIsConnecting] = useState(false);
  const [error, setError] = useState<string | null>(
    searchParams.get("error") ?? null,
  );

  useEffect(() => {
    let isMounted = true;

    async function loadSession() {
      try {
        const nextSession = await api.getSession();
        if (!isMounted) {
          return;
        }
        if (nextSession.authenticated) {
          setSession(nextSession);
        } else {
          setSession(null);
        }
      } catch (sessionError) {
        if (isMounted) {
          setError((sessionError as Error).message);
        }
      } finally {
        if (isMounted) {
          setIsLoading(false);
        }
      }
    }

    void loadSession();
    return () => {
      isMounted = false;
    };
  }, []);

  async function handleGoogleConnect() {
    setIsConnecting(true);
    setError(null);

    try {
      const result = await api.startGoogleAuth("/mail");
      window.location.href = result.authorization_url;
    } catch (connectError) {
      setError((connectError as Error).message);
      setIsConnecting(false);
    }
  }

  async function handleLogout() {
    setIsLoading(true);
    try {
      await api.logout();
      setSession(null);
    } catch (logoutError) {
      setError((logoutError as Error).message);
    } finally {
      setIsLoading(false);
    }
  }

  const linkedAccountCount = session?.linked_accounts?.length ?? 0;
  const sessionLabel =
    session?.account_name ??
    session?.user?.display_name ??
    session?.account_email ??
    session?.user?.primary_email ??
    "your Google account";

  return (
    <main className="grid h-full min-h-0 gap-5 rounded-[12px] border border-[var(--line)] bg-white p-5 shadow-[var(--shadow)] md:grid-cols-[minmax(0,1.05fr)_400px] md:gap-6 md:p-6">
      <section className="flex flex-col justify-between rounded-[18px] border border-[#e2e8f0] bg-[linear-gradient(180deg,#f8fafc_0%,#eef2ff_100%)] p-8">
        <div className="grid gap-8">
          <div className="grid gap-3">
            <span className="inline-flex w-fit rounded-full border border-[#cbd5e1] bg-white/80 px-3 py-1 text-[0.72rem] font-semibold uppercase tracking-[0.12em] text-[#334155]">
              Shared inbox workspace
            </span>
            <div>
              <h1 className="m-0 text-[2.3rem] font-semibold tracking-[-0.04em] text-[#0f172a]">
                InboxOS
              </h1>
              <p className="mt-3 max-w-[34rem] text-[1rem] leading-7 text-[#475569]">
                Connect Google once, then use the same mailbox and calendar
                across the web shell and desktop shell.
              </p>
            </div>
          </div>
          <div className="grid gap-3 sm:grid-cols-3">
            {[
              { label: "Gmail inbox threads", icon: Mail },
              { label: "Google Calendar events", icon: CalendarDays },
              { label: "Cookie-backed session redirect", icon: ArrowRight },
            ].map((item) => (
              <div
                key={item.label}
                className="rounded-[16px] border border-white/80 bg-white/85 p-4 shadow-[0_10px_24px_rgba(15,23,42,0.06)]"
              >
                <item.icon size={16} className="text-[#334155]" />
                <p className="mt-3 text-[0.88rem] font-medium text-[#0f172a]">
                  {item.label}
                </p>
              </div>
            ))}
          </div>
        </div>
        <p className="m-0 text-[0.95rem] font-medium text-[#1e293b]">
          Agentic first mail
        </p>
      </section>

      <section className="flex min-h-0 items-center justify-center">
        <div className="grid w-full max-w-[420px] gap-5 rounded-[18px] border border-[var(--line)] bg-white p-7 shadow-[0_18px_42px_rgba(15,23,42,0.08)]">
          <div className="grid gap-2">
            <h2 className="m-0 text-[1.2rem] font-semibold text-[var(--text)]">
              {session?.authenticated ? "Google Connected" : "Sign In"}
            </h2>
            <p className="m-0 text-[0.92rem] leading-6 text-[var(--muted)]">
              {session?.authenticated
                ? `Signed in as ${sessionLabel}.`
                : "Use Google OAuth to load your Gmail inbox and primary calendar."}
            </p>
          </div>
          {session?.authenticated && linkedAccountCount > 1 ? (
            <p className="m-0 rounded-[12px] border border-[#e2e8f0] bg-[#f8fafc] px-4 py-3 text-[0.82rem] text-[#475569]">
              {linkedAccountCount} linked accounts are available in this
              workspace.
            </p>
          ) : null}

          {error ? (
            <p className="m-0 rounded-[12px] border border-[#fecdd3] bg-[#fff1f2] px-4 py-3 text-[0.83rem] text-[#be123c]">
              {error}
            </p>
          ) : null}

          {session?.authenticated ? (
            <div className="grid gap-2">
              <Button type="button" onClick={() => router.push("/mail")}>
                Open Mail
              </Button>
              <Button
                type="button"
                variant="outline"
                onClick={() => router.push("/calendar")}
              >
                Open Calendar
              </Button>
              <Button
                type="button"
                variant="ghost"
                onClick={handleLogout}
                disabled={isLoading}
              >
                Sign Out
              </Button>
            </div>
          ) : (
            <Button
              type="button"
              className="h-11 rounded-[12px]"
              onClick={handleGoogleConnect}
              disabled={isConnecting || isLoading}
            >
              {isConnecting
                ? "Redirecting to Google..."
                : "Continue with Google"}
            </Button>
          )}
        </div>
      </section>
    </main>
  );
}
