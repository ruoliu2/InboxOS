"use client";

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { api } from "@inboxos/lib/api";
import { AuthSessionResponse } from "@inboxos/types";

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
    <main className="auth-layout panel-surface">
      <section className="auth-left">
        <div>
          <h1>InboxOS</h1>
          <p>
            Connect Google once, then use the same mailbox and calendar across
            the web shell and desktop shell.
          </p>
        </div>
        <div className="auth-feature-list">
          <p>Gmail inbox threads</p>
          <p>Google Calendar events</p>
          <p>Cookie-backed session redirect</p>
        </div>
        <blockquote>
          <p>
            One sign-in flow, then the app opens directly into mail instead of a
            mock workspace.
          </p>
          <footer>Google workspace mode</footer>
        </blockquote>
      </section>

      <section className="auth-right">
        <div className="auth-card">
          <h2>{session?.authenticated ? "Google Connected" : "Sign In"}</h2>
          <p>
            {session?.authenticated
              ? `Signed in as ${sessionLabel}.`
              : "Use Google OAuth to load your Gmail inbox and primary calendar."}
          </p>
          {session?.authenticated && linkedAccountCount > 1 ? (
            <p className="muted">
              {linkedAccountCount} linked accounts are available in this
              workspace.
            </p>
          ) : null}

          {error ? <p className="status error">{error}</p> : null}

          {session?.authenticated ? (
            <div className="auth-actions">
              <button
                className="btn btn-primary"
                type="button"
                onClick={() => router.push("/mail")}
              >
                Open Mail
              </button>
              <button type="button" onClick={() => router.push("/calendar")}>
                Open Calendar
              </button>
              <button type="button" onClick={handleLogout} disabled={isLoading}>
                Sign Out
              </button>
            </div>
          ) : (
            <button
              className="btn btn-primary auth-google-btn"
              type="button"
              onClick={handleGoogleConnect}
              disabled={isConnecting || isLoading}
            >
              {isConnecting
                ? "Redirecting to Google..."
                : "Continue with Google"}
            </button>
          )}
        </div>
      </section>
    </main>
  );
}
