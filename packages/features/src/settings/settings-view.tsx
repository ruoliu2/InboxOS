"use client";

import { useEffect, useMemo, useState } from "react";
import { Mail, Plus, ShieldCheck } from "lucide-react";

import { api } from "@inboxos/lib/api";
import { AuthSessionResponse, LinkedAccount } from "@inboxos/types";

function accountLabel(account: LinkedAccount): string {
  return (
    account.display_name ?? account.provider_account_ref ?? "Google account"
  );
}

function avatarInitials(account: LinkedAccount): string {
  return accountLabel(account)
    .split(" ")
    .map((chunk) => chunk[0] ?? "")
    .join("")
    .slice(0, 2)
    .toUpperCase();
}

export function SettingsView() {
  const [session, setSession] = useState<AuthSessionResponse | null>(null);
  const [accounts, setAccounts] = useState<LinkedAccount[]>([]);
  const [loading, setLoading] = useState(true);
  const [busyAccountId, setBusyAccountId] = useState<string | null>(null);
  const [connecting, setConnecting] = useState(false);
  const [signingOut, setSigningOut] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function loadState() {
    setLoading(true);
    setError(null);

    try {
      const [nextSession, nextAccounts] = await Promise.all([
        api.getSession(),
        api.getAccounts(),
      ]);
      if (!nextSession.authenticated) {
        window.location.href = "/auth";
        return;
      }
      setSession(nextSession);
      setAccounts(nextAccounts);
    } catch (loadError) {
      setError((loadError as Error).message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadState();
  }, []);

  const defaultAccountId = session?.active_account_id ?? null;
  const activeAccounts = useMemo(
    () => accounts.filter((account) => account.status === "active"),
    [accounts],
  );

  async function handleAddAccount() {
    setConnecting(true);
    setError(null);
    setMessage(null);

    try {
      const result = await api.startAccountConnect("google_gmail", "/settings");
      window.location.href = result.authorization_url;
    } catch (connectError) {
      setError((connectError as Error).message);
      setConnecting(false);
    }
  }

  async function handleSetDefault(accountId: string) {
    setBusyAccountId(accountId);
    setError(null);
    setMessage(null);

    try {
      const nextSession = await api.activateAccount(accountId);
      setSession(nextSession);
      setMessage("Default sending account updated.");
    } catch (activateError) {
      setError((activateError as Error).message);
    } finally {
      setBusyAccountId(null);
    }
  }

  async function handleDisconnect(accountId: string) {
    setBusyAccountId(accountId);
    setError(null);
    setMessage(null);

    try {
      await api.disconnectAccount(accountId);
      await loadState();
      setMessage("Account disconnected.");
    } catch (disconnectError) {
      setError((disconnectError as Error).message);
    } finally {
      setBusyAccountId(null);
    }
  }

  async function handleSignOut() {
    setSigningOut(true);
    setError(null);

    try {
      await api.logout();
      window.location.href = "/auth";
    } catch (logoutError) {
      setError((logoutError as Error).message);
      setSigningOut(false);
    }
  }

  return (
    <main className="settings-layout">
      <section className="panel-surface settings-hero">
        <div>
          <h1>Settings</h1>
          <p>
            Manage linked Google accounts. All active accounts appear in the
            combined inbox, calendar, and task views.
          </p>
        </div>
        <div className="settings-hero-meta">
          <div>
            <strong>{activeAccounts.length}</strong>
            <span>Active accounts</span>
          </div>
          <div>
            <strong>{accounts.length}</strong>
            <span>Linked total</span>
          </div>
        </div>
      </section>

      <section className="panel-surface settings-account-panel">
        <div className="settings-panel-header">
          <div>
            <h2>Connected Accounts</h2>
            <p>
              The default account is used for new calendar items and any other
              write action that starts outside a specific mailbox.
            </p>
          </div>
          <button
            className="btn btn-primary"
            type="button"
            onClick={handleAddAccount}
            disabled={connecting}
          >
            <Plus size={15} />
            {connecting ? "Connecting..." : "Add account"}
          </button>
        </div>

        {message ? <p className="status inline-status">{message}</p> : null}
        {error ? <p className="status error inline-status">{error}</p> : null}
        {loading ? <p className="list-empty">Loading accounts...</p> : null}

        {!loading ? (
          <div className="settings-account-list">
            {accounts.map((account) => {
              const isDefault = account.id === defaultAccountId;
              const isDisconnected = account.status !== "active";
              return (
                <article key={account.id} className="settings-account-card">
                  <div className="settings-account-main">
                    {account.avatar_url ? (
                      <img
                        src={account.avatar_url}
                        alt=""
                        className="settings-account-avatar"
                      />
                    ) : (
                      <div className="settings-account-avatar settings-account-avatar-fallback">
                        {avatarInitials(account)}
                      </div>
                    )}
                    <div className="settings-account-copy">
                      <div className="settings-account-title">
                        <strong>{accountLabel(account)}</strong>
                        {isDefault ? (
                          <span className="settings-default-pill">
                            <ShieldCheck size={13} />
                            Default
                          </span>
                        ) : null}
                      </div>
                      <p>{account.provider_account_ref}</p>
                      <div className="settings-account-notes">
                        <span>
                          {isDisconnected ? "Disconnected" : "Active"}
                        </span>
                        <span>Mail, Calendar</span>
                      </div>
                    </div>
                  </div>

                  <div className="settings-account-actions">
                    <button
                      type="button"
                      onClick={() => handleSetDefault(account.id)}
                      disabled={
                        isDefault ||
                        isDisconnected ||
                        busyAccountId === account.id
                      }
                    >
                      {busyAccountId === account.id && !isDefault
                        ? "Saving..."
                        : "Set as default"}
                    </button>
                    <button
                      type="button"
                      onClick={() => handleDisconnect(account.id)}
                      disabled={
                        isDisconnected ||
                        busyAccountId === account.id ||
                        (isDefault && activeAccounts.length === 1)
                      }
                    >
                      {busyAccountId === account.id && isDefault
                        ? "Disconnecting..."
                        : "Disconnect"}
                    </button>
                  </div>
                </article>
              );
            })}
          </div>
        ) : null}
      </section>

      <section className="panel-surface settings-routing-panel">
        <div>
          <h2>Account Routing</h2>
          <p>
            Combined views use every active account. Per-account mailbox groups
            remain available in Mail, and item-level account attribution is
            shown in mail and calendar detail.
          </p>
        </div>
        <div className="settings-routing-list">
          <div>
            <Mail size={15} />
            <span>Mail reads from all active accounts by default.</span>
          </div>
          <div>
            <ShieldCheck size={15} />
            <span>
              The default account stays available for new outgoing actions.
            </span>
          </div>
        </div>
        <button type="button" onClick={handleSignOut} disabled={signingOut}>
          {signingOut ? "Signing out..." : "Sign out"}
        </button>
      </section>
    </main>
  );
}
