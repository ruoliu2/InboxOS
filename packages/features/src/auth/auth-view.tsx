"use client";

import { FormEvent, useState } from "react";

import { api } from "@inboxos/lib/api";

export function AuthView() {
  const [email, setEmail] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [authUrl, setAuthUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  async function handleGoogleConnect() {
    setIsLoading(true);
    setError(null);
    setMessage(null);

    try {
      const result = await api.startGoogleAuth();
      setAuthUrl(result.authorization_url);
      setMessage("Google OAuth URL generated. Open it to continue sign-in.");
      if (typeof window !== "undefined") {
        window.open(result.authorization_url, "_blank", "noopener,noreferrer");
      }
    } catch (connectError) {
      setError((connectError as Error).message);
    } finally {
      setIsLoading(false);
    }
  }

  function handleEmailSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);

    if (!email.trim()) {
      setError("Email is required.");
      return;
    }

    setMessage(
      "Email sign-in is scaffolded for MVP. Use Google connect for now.",
    );
  }

  return (
    <main className="auth-layout panel-surface">
      <section className="auth-left">
        <div>
          <h1>InboxOS</h1>
          <p>Shared Mail-style experience across web and macOS.</p>
        </div>
        <blockquote>
          <p>
            “Mail-like UI with built-in AI actions made triage and follow-ups
            faster than switching across inbox, notes, and reminders.”
          </p>
          <footer>Early MVP user</footer>
        </blockquote>
      </section>

      <section className="auth-right">
        <div className="auth-card">
          <h2>Sign In</h2>
          <p>Use the same authentication flow for web and desktop clients.</p>

          <form onSubmit={handleEmailSubmit} className="auth-form">
            <label htmlFor="auth-email">Email</label>
            <input
              id="auth-email"
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              placeholder="name@example.com"
              autoComplete="email"
            />
            <button
              type="submit"
              className="btn btn-primary"
              disabled={isLoading}
            >
              Continue With Email
            </button>
          </form>

          <div className="auth-divider">or</div>

          <button
            className="btn"
            type="button"
            onClick={handleGoogleConnect}
            disabled={isLoading}
          >
            {isLoading ? "Connecting..." : "Connect Google"}
          </button>

          {error ? <p className="status error">{error}</p> : null}
          {message ? <p className="status">{message}</p> : null}
          {authUrl ? (
            <p className="muted auth-url" title={authUrl}>
              OAuth URL: {authUrl}
            </p>
          ) : null}
        </div>
      </section>
    </main>
  );
}
