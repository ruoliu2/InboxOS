"use client";

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { ArrowRight, CalendarDays, CheckCheck, Mail } from "lucide-react";

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
  const capabilityCards = [
    {
      icon: Mail,
      title: "Mail triage",
      body: "Review threads, draft replies, and keep context in one focused workspace.",
    },
    {
      icon: CalendarDays,
      title: "Calendar flow",
      body: "Move between schedule planning and event details without losing orientation.",
    },
    {
      icon: CheckCheck,
      title: "Task capture",
      body: "Turn inbox commitments into tracked work with lightweight structure.",
    },
  ];

  return (
    <main className="grid h-full min-h-0 gap-6 overflow-hidden rounded-[28px] border border-[color:var(--line)] bg-[rgba(255,255,255,0.72)] p-4 shadow-[var(--shadow-soft)] backdrop-blur-xl md:grid-cols-[minmax(0,1.15fr)_430px] md:p-6">
      <section className="relative overflow-hidden rounded-[24px] border border-white/70 bg-[radial-gradient(circle_at_top_left,rgba(255,255,255,0.94),rgba(236,244,255,0.9)_48%,rgba(222,232,255,0.92)_100%)] p-8 shadow-[0_32px_72px_rgba(15,23,42,0.12)]">
        <div className="pointer-events-none absolute inset-x-0 top-0 h-56 bg-[radial-gradient(circle_at_top,rgba(37,99,235,0.22),transparent_72%)]" />
        <div className="relative flex h-full flex-col justify-between gap-10">
          <div className="grid gap-5">
            <span className="inline-flex w-fit rounded-full border border-white/80 bg-white/75 px-4 py-1.5 text-[0.7rem] font-semibold uppercase tracking-[0.18em] text-[#1e3a8a] shadow-[0_12px_24px_rgba(37,99,235,0.12)]">
              Shared inbox workspace
            </span>
            <div className="grid gap-4">
              <h1 className="m-0 max-w-[12ch] text-[clamp(3rem,6vw,5.4rem)] font-semibold leading-[0.92] tracking-[-0.07em] text-[#0f172a]">
                Calm control for busy inboxes.
              </h1>
              <p className="m-0 max-w-[40rem] text-[1.02rem] leading-7 text-[#475569]">
                InboxOS brings mail, calendar, and task follow-through into one
                sharper workspace. Connect Google once and move through the day
                without bouncing between tools.
              </p>
            </div>
          </div>
          <div className="grid gap-3 md:grid-cols-3">
            {capabilityCards.map((item) => (
              <article
                key={item.title}
                className="rounded-[20px] border border-white/80 bg-white/72 p-4 shadow-[0_18px_40px_rgba(15,23,42,0.08)] backdrop-blur"
              >
                <div className="mb-4 inline-flex h-11 w-11 items-center justify-center rounded-[14px] bg-[#eff6ff] text-[#1d4ed8] shadow-[inset_0_1px_0_rgba(255,255,255,0.9)]">
                  <item.icon size={18} />
                </div>
                <h2 className="m-0 text-[0.98rem] font-semibold tracking-[-0.02em] text-[#0f172a]">
                  {item.title}
                </h2>
                <p className="mt-2 text-[0.88rem] leading-6 text-[#526072]">
                  {item.body}
                </p>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section className="flex min-h-0 items-center justify-center">
        <div className="grid w-full max-w-[430px] gap-6 rounded-[24px] border border-white/70 bg-[rgba(255,255,255,0.88)] p-7 shadow-[0_28px_72px_rgba(15,23,42,0.18)] backdrop-blur-xl">
          <div className="grid gap-2">
            <span className="text-[0.72rem] font-semibold uppercase tracking-[0.16em] text-[color:var(--accent-strong)]">
              {session?.authenticated ? "Workspace ready" : "Connect Google"}
            </span>
            <h2 className="m-0 text-[1.6rem] font-semibold tracking-[-0.04em] text-[var(--text)]">
              {session?.authenticated ? "Google Connected" : "Sign In"}
            </h2>
            <p className="m-0 text-[0.94rem] leading-7 text-[color:var(--text-muted)]">
              {session?.authenticated
                ? `Signed in as ${sessionLabel}.`
                : "Use Google OAuth to unlock your Gmail inbox, primary calendar, and lightweight task workspace."}
            </p>
          </div>
          {session?.authenticated && linkedAccountCount > 1 ? (
            <p className="m-0 rounded-[16px] border border-[color:var(--line)] bg-[color:var(--surface-1)] px-4 py-3 text-[0.84rem] text-[color:var(--text-muted)]">
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
              <Button
                type="button"
                className="h-12 justify-between rounded-[16px] px-4"
                onClick={() => router.push("/mail")}
              >
                Open Mail
                <ArrowRight size={16} />
              </Button>
              <Button
                type="button"
                variant="outline"
                className="h-12 justify-between rounded-[16px] px-4"
                onClick={() => router.push("/calendar")}
              >
                Open Calendar
                <ArrowRight size={16} />
              </Button>
              <Button
                type="button"
                variant="ghost"
                className="mt-1 h-11 rounded-[16px]"
                onClick={handleLogout}
                disabled={isLoading}
              >
                Sign Out
              </Button>
            </div>
          ) : (
            <Button
              type="button"
              className="h-12 rounded-[16px] text-[0.9rem]"
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
