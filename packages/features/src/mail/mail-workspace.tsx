"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Archive,
  ArchiveX,
  ChevronDown,
  Clock,
  Forward,
  Inbox,
  LogOut,
  Mailbox,
  MoreVertical,
  Reply,
  ReplyAll,
  Search,
  Send,
  Trash2,
  Triangle,
} from "lucide-react";

import { api } from "@inboxos/lib/api";
import { formatDate } from "@inboxos/lib/format";
import {
  AuthSessionResponse,
  ThreadDetail,
  ThreadSummary,
} from "@inboxos/types";

type ListTab = "all" | "unread";

type MailWorkspaceProps = {
  initialThreadId?: string | null;
};

const PAGE_SIZE = 20;

const primaryFolders = [
  { key: "inbox", label: "Inbox", icon: Inbox },
  { key: "sent", label: "Sent", icon: Send },
  { key: "archive", label: "Archive", icon: Archive },
  { key: "trash", label: "Trash", icon: Trash2 },
  { key: "junk", label: "Junk", icon: ArchiveX },
] as const;

function isUnread(thread: ThreadSummary): boolean {
  return thread.action_states.some((state) => state !== "fyi");
}

function normalizedEmail(value: string | null | undefined): string | null {
  const normalized = value?.trim().toLowerCase();
  return normalized && normalized.includes("@") ? normalized : null;
}

function counterpartyEmailFromThread(
  thread: ThreadSummary | ThreadDetail,
  accountEmail?: string | null,
): string {
  const currentAccount = normalizedEmail(accountEmail);
  const otherParticipant = thread.participants.find((value) => {
    const participant = normalizedEmail(value);
    return participant !== null && participant !== currentAccount;
  });

  return (
    otherParticipant ??
    thread.participants.find((value) => normalizedEmail(value) !== null) ??
    "unknown@example.com"
  );
}

function displayNameFromThread(
  thread: ThreadSummary | ThreadDetail,
  accountEmail?: string | null,
): string {
  const email = counterpartyEmailFromThread(thread, accountEmail);
  const base = email
    .split("@")[0]
    .replace(/[._-]+/g, " ")
    .trim();
  if (!base) {
    return "Unknown";
  }
  return base
    .split(" ")
    .map((chunk) => `${chunk[0]?.toUpperCase() ?? ""}${chunk.slice(1)}`)
    .join(" ");
}

function initials(value: string): string {
  return value
    .split(" ")
    .map((chunk) => chunk[0] ?? "")
    .join("")
    .slice(0, 2)
    .toUpperCase();
}

function relativeTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "recent";
  }

  const diffMs = Date.now() - date.getTime();
  const diffHours = Math.floor(diffMs / (1000 * 60 * 60));
  const diffDays = Math.floor(diffHours / 24);
  const diffMonths = Math.floor(diffDays / 30);

  if (diffHours < 24) {
    return `${Math.max(diffHours, 1)} hour${diffHours === 1 ? "" : "s"} ago`;
  }
  if (diffDays < 30) {
    return `${Math.max(diffDays, 1)} day${diffDays === 1 ? "" : "s"} ago`;
  }
  return `${Math.max(diffMonths, 1)} month${diffMonths === 1 ? "" : "s"} ago`;
}

function labelsFromThread(thread: ThreadSummary): string[] {
  if (thread.action_states.includes("to_reply")) {
    return ["unread"];
  }
  return ["gmail"];
}

function toThreadSummary(thread: ThreadDetail): ThreadSummary {
  return {
    id: thread.id,
    subject: thread.subject,
    snippet: thread.snippet,
    participants: thread.participants,
    last_message_at: thread.last_message_at,
    action_states: thread.action_states,
  };
}

function mergeThreadSummaries(
  current: ThreadSummary[],
  incoming: ThreadSummary[],
  position: "append" | "prepend" = "append",
): ThreadSummary[] {
  if (incoming.length === 0) {
    return current;
  }

  const incomingById = new Map(incoming.map((thread) => [thread.id, thread]));
  if (position === "prepend") {
    return [
      ...incoming,
      ...current.filter((thread) => !incomingById.has(thread.id)),
    ];
  }

  const existingIds = new Set(current.map((thread) => thread.id));
  return [
    ...current.map((thread) => incomingById.get(thread.id) ?? thread),
    ...incoming.filter((thread) => !existingIds.has(thread.id)),
  ];
}

export function MailWorkspace({ initialThreadId }: MailWorkspaceProps) {
  const [session, setSession] = useState<AuthSessionResponse | null>(null);
  const [threads, setThreads] = useState<ThreadSummary[]>([]);
  const [selectedThreadId, setSelectedThreadId] = useState<string | null>(
    initialThreadId ?? null,
  );
  const [selectedThread, setSelectedThread] = useState<ThreadDetail | null>(
    null,
  );
  const [listTab, setListTab] = useState<ListTab>("all");
  const [search, setSearch] = useState("");
  const [replyText, setReplyText] = useState("");
  const [muteThread, setMuteThread] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loadingList, setLoadingList] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [loadingThread, setLoadingThread] = useState(false);
  const [sendingReply, setSendingReply] = useState(false);
  const [nextPageToken, setNextPageToken] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const threadRequestIdRef = useRef(0);
  const listScrollerRef = useRef<HTMLDivElement | null>(null);
  const loadMoreTriggerRef = useRef<HTMLDivElement | null>(null);

  const loadedSearchMode = search.trim().length > 0;

  const loadInitialThreads = useCallback(async () => {
    setLoadingList(true);
    setError(null);

    try {
      const [nextSession, page] = await Promise.all([
        api.getSession(),
        api.getGmailThreads({ page_size: PAGE_SIZE }),
      ]);
      if (!nextSession.authenticated) {
        window.location.href = "/auth";
        return;
      }

      setSession(nextSession);
      setThreads((current) => mergeThreadSummaries(page.threads, current));
      setNextPageToken(page.next_page_token);
      setHasMore(page.has_more);
      setNotice(
        page.threads.length === 0 ? "No Gmail inbox threads were found." : null,
      );
    } catch (loadError) {
      setError((loadError as Error).message);
      setThreads([]);
      setNextPageToken(null);
      setHasMore(false);
    } finally {
      setLoadingList(false);
    }
  }, []);

  const loadMoreThreads = useCallback(async () => {
    if (!nextPageToken || loadingList || loadingMore || loadedSearchMode) {
      return;
    }

    setLoadingMore(true);
    setError(null);

    try {
      const page = await api.getGmailThreads({
        page_token: nextPageToken,
        page_size: PAGE_SIZE,
      });
      setThreads((current) => mergeThreadSummaries(current, page.threads));
      setNextPageToken(page.next_page_token);
      setHasMore(page.has_more);
    } catch (loadError) {
      setError((loadError as Error).message);
    } finally {
      setLoadingMore(false);
    }
  }, [loadedSearchMode, loadingList, loadingMore, nextPageToken]);

  useEffect(() => {
    void loadInitialThreads();
  }, [loadInitialThreads]);

  useEffect(() => {
    if (!selectedThreadId) {
      threadRequestIdRef.current += 1;
      setSelectedThread(null);
      setLoadingThread(false);
      return;
    }

    const requestId = threadRequestIdRef.current + 1;
    threadRequestIdRef.current = requestId;
    setSelectedThread(null);
    setLoadingThread(true);
    setError(null);

    void api
      .getGmailThread(selectedThreadId)
      .then((data) => {
        if (threadRequestIdRef.current !== requestId) {
          return;
        }
        setSelectedThread(data);
        setThreads((current) =>
          mergeThreadSummaries(
            current,
            [toThreadSummary(data)],
            current.some((thread) => thread.id === data.id)
              ? "append"
              : "prepend",
          ),
        );
      })
      .catch((loadError) => {
        if (threadRequestIdRef.current !== requestId) {
          return;
        }
        setSelectedThread(null);
        setError((loadError as Error).message);
      })
      .finally(() => {
        if (threadRequestIdRef.current === requestId) {
          setLoadingThread(false);
        }
      });
  }, [selectedThreadId]);

  useEffect(() => {
    if (
      loadingList ||
      loadingMore ||
      loadedSearchMode ||
      !hasMore ||
      !loadMoreTriggerRef.current
    ) {
      return;
    }

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          void loadMoreThreads();
        }
      },
      {
        root: listScrollerRef.current,
        rootMargin: "0px 0px 160px 0px",
      },
    );

    observer.observe(loadMoreTriggerRef.current);
    return () => {
      observer.disconnect();
    };
  }, [hasMore, loadedSearchMode, loadMoreThreads, loadingList, loadingMore]);

  const activeThread =
    selectedThread && selectedThread.id === selectedThreadId
      ? selectedThread
      : null;

  const visibleThreads = useMemo(() => {
    const query = search.trim().toLowerCase();

    return threads.filter((thread) => {
      if (listTab === "unread" && !isUnread(thread)) {
        return false;
      }

      if (!query) {
        return true;
      }

      const haystack = [
        thread.subject,
        thread.snippet,
        thread.participants.join(" "),
      ]
        .join(" ")
        .toLowerCase();
      return haystack.includes(query);
    });
  }, [listTab, search, threads]);

  async function sendReply() {
    if (!selectedThreadId || !activeThread) {
      return;
    }

    const body = replyText.trim();
    if (!body) {
      setError("Reply cannot be empty.");
      return;
    }

    setError(null);
    setNotice(null);
    setSendingReply(true);

    try {
      const result = await api.replyToGmailThread(selectedThreadId, {
        body,
        mute_thread: muteThread,
      });
      setSelectedThread(result.thread);
      setThreads((current) =>
        mergeThreadSummaries(
          current,
          [toThreadSummary(result.thread)],
          "prepend",
        ),
      );
      setReplyText("");
      setMuteThread(false);
      setNotice(
        result.muted
          ? "Reply sent through Gmail. Mute is not applied to Gmail labels."
          : "Reply sent through Gmail.",
      );
    } catch (sendError) {
      setError((sendError as Error).message);
    } finally {
      setSendingReply(false);
    }
  }

  async function signOut() {
    try {
      await api.logout();
    } finally {
      window.location.href = "/auth";
    }
  }

  const accountLabel =
    session?.account_name ?? session?.account_email ?? "Google account";

  return (
    <main className="mail-shell panel-surface">
      <aside className="mail-left-nav">
        <div className="mail-account-select">
          <span className="account-logo" aria-hidden>
            <Triangle size={11} />
          </span>
          <span className="account-name">{accountLabel}</span>
          <span className="account-caret" aria-hidden>
            <ChevronDown size={14} />
          </span>
        </div>

        <div className="mail-folder-group">
          {primaryFolders.map((folder) => {
            const count = folder.key === "inbox" ? threads.length : 0;
            return (
              <button
                key={folder.key}
                className={`folder-row ${folder.key === "inbox" ? "active" : ""}`.trim()}
                type="button"
                disabled={folder.key !== "inbox"}
              >
                <span className="folder-label">
                  <folder.icon size={15} />
                  {folder.label}
                </span>
                <span className="folder-count">{count || ""}</span>
              </button>
            );
          })}
        </div>

        <div className="mail-folder-group">
          <p className="folder-note">
            Gmail inbox is live. Other folders are left as shell navigation for
            now.
          </p>
          <button
            className="folder-row signout-row"
            onClick={signOut}
            type="button"
          >
            <span className="folder-label">
              <LogOut size={15} />
              Sign Out
            </span>
          </button>
        </div>
      </aside>

      <section className="mail-center-list">
        <div className="list-topbar">
          <h1>Inbox</h1>
          <div className="list-tabs">
            <button
              className={listTab === "all" ? "active" : ""}
              onClick={() => setListTab("all")}
              type="button"
            >
              All mail
            </button>
            <button
              className={listTab === "unread" ? "active" : ""}
              onClick={() => setListTab("unread")}
              type="button"
            >
              Unread
            </button>
          </div>
        </div>

        <div className="mail-search-wrap">
          <div className="search-field">
            <Search size={16} />
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search loaded threads"
              aria-label="Search mails"
            />
          </div>
        </div>

        {notice ? <p className="status inline-status">{notice}</p> : null}
        {loadedSearchMode ? (
          <p className="status inline-status">Searching loaded threads only.</p>
        ) : null}
        {error ? <p className="status error inline-status">{error}</p> : null}
        {loadingList ? (
          <p className="list-empty">Loading Gmail inbox...</p>
        ) : null}

        {!loadingList ? (
          <div className="mail-card-list" ref={listScrollerRef}>
            {visibleThreads.length === 0 && !error ? (
              <p className="list-empty">
                {loadedSearchMode
                  ? "No matches in the loaded Gmail threads."
                  : "No messages in this Gmail inbox."}
              </p>
            ) : null}
            {visibleThreads.map((thread) => {
              const name = displayNameFromThread(
                thread,
                session?.account_email,
              );
              const labels = labelsFromThread(thread);
              return (
                <button
                  key={thread.id}
                  className={`mail-card ${thread.id === selectedThreadId ? "active" : ""}`.trim()}
                  onClick={() => {
                    if (thread.id === selectedThreadId) {
                      return;
                    }
                    setSelectedThread(null);
                    setLoadingThread(true);
                    setError(null);
                    setSelectedThreadId(thread.id);
                  }}
                  type="button"
                >
                  <div className="mail-card-row">
                    <strong>{name}</strong>
                    <span>{relativeTime(thread.last_message_at)}</span>
                  </div>
                  <p className="mail-card-subject">{thread.subject}</p>
                  <p className="mail-card-snippet">{thread.snippet}</p>
                  <div className="mail-card-labels">
                    {labels.map((label) => (
                      <span
                        key={`${thread.id}-${label}`}
                        className="label-pill"
                      >
                        {label}
                      </span>
                    ))}
                  </div>
                </button>
              );
            })}

            {!loadedSearchMode && hasMore ? (
              <div className="mail-list-footer">
                {loadingMore ? <span>Loading older mail...</span> : null}
                <div
                  ref={loadMoreTriggerRef}
                  className="mail-list-sentinel"
                  aria-hidden
                />
              </div>
            ) : null}
          </div>
        ) : null}
      </section>

      <section className="mail-read-pane">
        <div className="read-toolbar">
          <button type="button" aria-label="Archive">
            <Archive size={15} />
          </button>
          <button type="button" aria-label="Move to junk">
            <ArchiveX size={15} />
          </button>
          <button type="button" aria-label="Move to trash">
            <Trash2 size={15} />
          </button>
          <button type="button" aria-label="Snooze">
            <Clock size={15} />
          </button>
          <div className="spacer" />
          <div className="toolbar-sep" />
          <button type="button" aria-label="Reply">
            <Reply size={15} />
          </button>
          <button type="button" aria-label="Reply all">
            <ReplyAll size={15} />
          </button>
          <button type="button" aria-label="Forward">
            <Forward size={15} />
          </button>
          <div className="toolbar-sep" />
          <button type="button" aria-label="More">
            <MoreVertical size={15} />
          </button>
        </div>

        {selectedThreadId && loadingThread ? (
          <p className="read-empty">Loading message...</p>
        ) : null}
        {selectedThreadId && !loadingThread && !activeThread && error ? (
          <div className="read-empty empty-thread-state">
            <Mailbox size={18} />
            <span>{error}</span>
          </div>
        ) : null}

        {activeThread ? (
          <>
            <div className="read-header">
              <div className="avatar-circle">
                {initials(
                  displayNameFromThread(activeThread, session?.account_email),
                )}
              </div>
              <div>
                <strong>
                  {displayNameFromThread(activeThread, session?.account_email)}
                </strong>
                <p>{activeThread.subject}</p>
                <p>
                  Reply-To:{" "}
                  {counterpartyEmailFromThread(
                    activeThread,
                    session?.account_email,
                  )}
                </p>
              </div>
              <time>{formatDate(activeThread.last_message_at)}</time>
            </div>

            <div className="read-body message-stack">
              {activeThread.messages.map((message) => (
                <article key={message.id} className="message-card">
                  <header className="message-card-header">
                    <strong>{message.sender}</strong>
                    <time>{formatDate(message.sent_at)}</time>
                  </header>
                  <p>{message.body || "No preview available."}</p>
                </article>
              ))}
            </div>

            <div className="reply-panel">
              <textarea
                value={replyText}
                onChange={(event) => setReplyText(event.target.value)}
                placeholder={`Reply ${displayNameFromThread(activeThread, session?.account_email)}...`}
              />
              <div className="reply-actions">
                <label>
                  <input
                    type="checkbox"
                    checked={muteThread}
                    onChange={(event) => setMuteThread(event.target.checked)}
                  />
                  Keep InboxOS muted after send
                </label>
                <button
                  className="send-button"
                  onClick={sendReply}
                  type="button"
                  disabled={sendingReply}
                >
                  {sendingReply ? "Sending..." : "Send"}
                </button>
              </div>
            </div>
          </>
        ) : null}

        {!activeThread && !selectedThreadId && !loadingThread && !error ? (
          <div className="read-empty empty-thread-state">
            <Mailbox size={18} />
            <span>Select a Gmail thread to read it here.</span>
          </div>
        ) : null}
      </section>
    </main>
  );
}
