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
  ComposeMode,
  MailboxKey,
  ThreadActionName,
  ThreadDetail,
  ThreadMessage,
  ThreadSummary,
} from "@inboxos/types";
import { ConfirmDialog } from "@inboxos/ui/confirm-dialog";
import { OverflowMenu } from "@inboxos/ui/overflow-menu";

import { EmailHtmlPreview } from "./email-html-preview";

type ListTab = "all" | "unread";

type MailWorkspaceProps = {
  initialThreadId?: string | null;
};

type ConfirmState = {
  title: string;
  body: string;
  confirmLabel: string;
  action: ThreadActionName;
} | null;

const PAGE_SIZE = 20;

const primaryFolders: Array<{
  key: MailboxKey;
  label: string;
  icon: typeof Inbox;
}> = [
  { key: "inbox", label: "Inbox", icon: Inbox },
  { key: "sent", label: "Sent", icon: Send },
  { key: "archive", label: "Archive", icon: Archive },
  { key: "trash", label: "Trash", icon: Trash2 },
  { key: "junk", label: "Junk", icon: ArchiveX },
];

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

function mailboxHeading(value: MailboxKey): string {
  return (
    primaryFolders.find((folder) => folder.key === value)?.label ?? "Inbox"
  );
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

function parseRecipients(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function hasHtmlPreview(message: ThreadMessage): boolean {
  return Boolean(message.body_html?.trim());
}

export function MailWorkspace({ initialThreadId }: MailWorkspaceProps) {
  const [session, setSession] = useState<AuthSessionResponse | null>(null);
  const [sessionChecked, setSessionChecked] = useState(false);
  const [mailboxCount, setMailboxCount] = useState<number | null>(null);
  const [threads, setThreads] = useState<ThreadSummary[]>([]);
  const [selectedThreadId, setSelectedThreadId] = useState<string | null>(
    initialThreadId ?? null,
  );
  const [selectedThread, setSelectedThread] = useState<ThreadDetail | null>(
    null,
  );
  const [mailbox, setMailbox] = useState<MailboxKey>("inbox");
  const [listTab, setListTab] = useState<ListTab>("all");
  const [searchInput, setSearchInput] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [composeMode, setComposeMode] = useState<ComposeMode>("reply");
  const [composeBody, setComposeBody] = useState("");
  const [forwardTo, setForwardTo] = useState("");
  const [forwardCc, setForwardCc] = useState("");
  const [forwardBcc, setForwardBcc] = useState("");
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loadingList, setLoadingList] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [loadingThread, setLoadingThread] = useState(false);
  const [sendingCompose, setSendingCompose] = useState(false);
  const [actionInFlight, setActionInFlight] = useState<ThreadActionName | null>(
    null,
  );
  const [nextPageToken, setNextPageToken] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [confirmState, setConfirmState] = useState<ConfirmState>(null);
  const [showMoreMenu, setShowMoreMenu] = useState(false);
  const threadRequestIdRef = useRef(0);
  const listScrollerRef = useRef<HTMLDivElement | null>(null);
  const loadMoreTriggerRef = useRef<HTMLDivElement | null>(null);
  const composerRef = useRef<HTMLTextAreaElement | null>(null);

  const unreadOnly = listTab === "unread";
  const activeHeading = mailboxHeading(mailbox);

  const loadInitialThreads = useCallback(async () => {
    if (!session?.authenticated) {
      return;
    }

    setLoadingList(true);
    setError(null);
    setNotice(null);

    try {
      const page = await api.getGmailThreads({
        page_size: PAGE_SIZE,
        q: searchQuery || undefined,
        mailbox,
        unread_only: unreadOnly,
      });
      setThreads(page.threads);
      setMailboxCount(page.total_count);
      setNextPageToken(page.next_page_token);
      setHasMore(page.has_more);
      if (page.threads.length === 0) {
        setNotice(`No ${activeHeading.toLowerCase()} threads were found.`);
      }
    } catch (loadError) {
      setError((loadError as Error).message);
      setMailboxCount(null);
      setThreads([]);
      setNextPageToken(null);
      setHasMore(false);
    } finally {
      setLoadingList(false);
    }
  }, [activeHeading, mailbox, searchQuery, session?.authenticated, unreadOnly]);

  const loadMoreThreads = useCallback(async () => {
    if (
      !session?.authenticated ||
      !nextPageToken ||
      loadingList ||
      loadingMore
    ) {
      return;
    }

    setLoadingMore(true);
    setError(null);
    setNotice(null);

    try {
      const page = await api.getGmailThreads({
        page_token: nextPageToken,
        page_size: PAGE_SIZE,
        q: searchQuery || undefined,
        mailbox,
        unread_only: unreadOnly,
      });
      setThreads((current) => mergeThreadSummaries(current, page.threads));
      setMailboxCount(page.total_count);
      setNextPageToken(page.next_page_token);
      setHasMore(page.has_more);
    } catch (loadError) {
      setError((loadError as Error).message);
    } finally {
      setLoadingMore(false);
    }
  }, [
    loadingList,
    loadingMore,
    mailbox,
    nextPageToken,
    searchQuery,
    session?.authenticated,
    unreadOnly,
  ]);

  useEffect(() => {
    let isMounted = true;

    async function loadSession() {
      try {
        const nextSession = await api.getSession();
        if (!isMounted) {
          return;
        }
        if (!nextSession.authenticated) {
          window.location.href = "/auth";
          return;
        }
        setSession(nextSession);
      } catch (sessionError) {
        if (isMounted) {
          setError((sessionError as Error).message);
        }
      } finally {
        if (isMounted) {
          setSessionChecked(true);
        }
      }
    }

    void loadSession();
    return () => {
      isMounted = false;
    };
  }, []);

  useEffect(() => {
    const handle = window.setTimeout(() => {
      setSearchQuery(searchInput.trim());
    }, 250);
    return () => {
      window.clearTimeout(handle);
    };
  }, [searchInput]);

  useEffect(() => {
    if (!sessionChecked || !session?.authenticated) {
      return;
    }
    setSelectedThreadId(null);
    setSelectedThread(null);
    setShowMoreMenu(false);
    void loadInitialThreads();
  }, [loadInitialThreads, session?.authenticated, sessionChecked]);

  useEffect(() => {
    setComposeMode("reply");
    setComposeBody("");
    setForwardTo("");
    setForwardCc("");
    setForwardBcc("");
  }, [selectedThreadId]);

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
    if (loadingList || loadingMore || !hasMore || !loadMoreTriggerRef.current) {
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
  }, [hasMore, loadMoreThreads, loadingList, loadingMore]);

  const activeThread =
    selectedThread && selectedThread.id === selectedThreadId
      ? selectedThread
      : null;

  const accountLabel =
    session?.account_name ?? session?.account_email ?? "Google account";

  function focusComposer(mode: ComposeMode) {
    setComposeMode(mode);
    setNotice(null);
    setError(null);
    window.requestAnimationFrame(() => {
      composerRef.current?.focus();
    });
  }

  const runThreadAction = useCallback(
    async (action: ThreadActionName) => {
      if (!selectedThreadId) {
        return;
      }

      setActionInFlight(action);
      setNotice(null);
      setError(null);

      try {
        const result = await api.actOnGmailThread(selectedThreadId, action);
        const shouldClearSelection =
          action === "delete" ||
          action === "restore" ||
          action === "trash" ||
          (action === "archive" && mailbox === "inbox") ||
          (action === "junk" && mailbox !== "junk");

        const updatedThread = result.thread;
        if (updatedThread) {
          setSelectedThread(updatedThread);
          setThreads((current) =>
            mergeThreadSummaries(
              current,
              [toThreadSummary(updatedThread)],
              "prepend",
            ),
          );
        }

        if (shouldClearSelection || result.deleted) {
          setSelectedThreadId(null);
          setSelectedThread(null);
        }

        await loadInitialThreads();
        setNotice(
          {
            archive: "Thread archived.",
            junk: "Thread moved to junk.",
            trash: "Thread moved to trash.",
            delete: "Thread deleted permanently.",
            restore: "Thread restored to inbox.",
          }[action],
        );
      } catch (actionError) {
        setError((actionError as Error).message);
      } finally {
        setActionInFlight(null);
        setConfirmState(null);
      }
    },
    [loadInitialThreads, mailbox, selectedThreadId],
  );

  const moreMenuItems = useMemo(() => {
    const items: Array<{
      label: string;
      onSelect: () => void;
      danger?: boolean;
      disabled?: boolean;
    }> = [];

    if (mailbox === "trash" || mailbox === "junk") {
      items.push({
        label: "Restore to inbox",
        onSelect: () => {
          void runThreadAction("restore");
        },
      });
    }
    if (mailbox === "trash") {
      items.push({
        label: "Delete permanently",
        onSelect: () =>
          setConfirmState({
            title: "Delete this thread permanently?",
            body: "This removes the Gmail thread permanently and cannot be undone.",
            confirmLabel: "Delete forever",
            action: "delete",
          }),
        danger: true,
      });
    }
    return items;
  }, [mailbox, runThreadAction]);

  async function sendCompose() {
    if (!selectedThreadId || !activeThread) {
      return;
    }

    setSendingCompose(true);
    setNotice(null);
    setError(null);

    try {
      const result = await api.composeGmailThread(selectedThreadId, {
        mode: composeMode,
        body: composeBody,
        to: parseRecipients(forwardTo),
        cc: parseRecipients(forwardCc),
        bcc: parseRecipients(forwardBcc),
      });
      setSelectedThread(result.thread);
      setThreads((current) =>
        mergeThreadSummaries(
          current,
          [toThreadSummary(result.thread)],
          "prepend",
        ),
      );
      setComposeBody("");
      setForwardTo("");
      setForwardCc("");
      setForwardBcc("");
      setComposeMode("reply");
      setNotice(
        {
          reply: "Reply sent through Gmail.",
          reply_all: "Reply all sent through Gmail.",
          forward: "Forward sent through Gmail.",
        }[result.mode],
      );
    } catch (composeError) {
      setError((composeError as Error).message);
    } finally {
      setSendingCompose(false);
    }
  }

  async function signOut() {
    try {
      await api.logout();
    } finally {
      window.location.href = "/auth";
    }
  }

  return (
    <>
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
              const count = folder.key === mailbox ? mailboxCount : 0;
              return (
                <button
                  key={folder.key}
                  className={`folder-row ${folder.key === mailbox ? "active" : ""}`.trim()}
                  onClick={() => setMailbox(folder.key)}
                  type="button"
                >
                  <span className="folder-label">
                    <folder.icon size={15} />
                    {folder.label}
                  </span>
                  <span className="folder-count">{count ?? ""}</span>
                </button>
              );
            })}
          </div>

          <div className="mail-folder-group">
            <p className="folder-note">
              Gmail folders and search now reflect live mailbox state.
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
            <h1>{activeHeading}</h1>
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
                value={searchInput}
                onChange={(event) => setSearchInput(event.target.value)}
                placeholder="Search Gmail"
                aria-label="Search Gmail"
              />
            </div>
          </div>

          {notice ? <p className="status inline-status">{notice}</p> : null}
          {error ? <p className="status error inline-status">{error}</p> : null}
          {loadingList ? (
            <p className="list-empty">Loading Gmail threads...</p>
          ) : null}

          {!loadingList ? (
            <div className="mail-card-list" ref={listScrollerRef}>
              {threads.length === 0 && !error ? (
                <p className="list-empty">No messages in this Gmail view.</p>
              ) : null}
              {threads.map((thread) => {
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

              {hasMore ? (
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
            <button
              type="button"
              aria-label="Archive"
              onClick={() => void runThreadAction("archive")}
              disabled={
                !activeThread ||
                mailbox === "archive" ||
                actionInFlight !== null
              }
            >
              <Archive size={15} />
            </button>
            <button
              type="button"
              aria-label="Move to junk"
              onClick={() => void runThreadAction("junk")}
              disabled={
                !activeThread || mailbox === "junk" || actionInFlight !== null
              }
            >
              <ArchiveX size={15} />
            </button>
            <button
              type="button"
              aria-label="Move to trash"
              onClick={() =>
                setConfirmState({
                  title: "Move this thread to trash?",
                  body: "The Gmail thread will move to trash and can be restored from the trash view.",
                  confirmLabel: "Move to trash",
                  action: "trash",
                })
              }
              disabled={!activeThread || actionInFlight !== null}
            >
              <Trash2 size={15} />
            </button>
            <button
              type="button"
              aria-label="Snooze unavailable"
              className="disabled-toolbar-button"
              onClick={() =>
                setNotice(
                  "Snooze is not exposed by the Gmail thread API. This control is intentionally disabled.",
                )
              }
              disabled={!activeThread}
            >
              <Clock size={15} />
            </button>
            <div className="spacer" />
            <div className="toolbar-sep" />
            <button
              type="button"
              aria-label="Reply"
              onClick={() => focusComposer("reply")}
              disabled={!activeThread}
            >
              <Reply size={15} />
            </button>
            <button
              type="button"
              aria-label="Reply all"
              onClick={() => focusComposer("reply_all")}
              disabled={!activeThread}
            >
              <ReplyAll size={15} />
            </button>
            <button
              type="button"
              aria-label="Forward"
              onClick={() => focusComposer("forward")}
              disabled={!activeThread}
            >
              <Forward size={15} />
            </button>
            <div className="toolbar-sep" />
            <div className="toolbar-menu-wrap">
              <button
                type="button"
                aria-label="More"
                onClick={() => setShowMoreMenu((current) => !current)}
                disabled={!activeThread || moreMenuItems.length === 0}
              >
                <MoreVertical size={15} />
              </button>
              <OverflowMenu
                open={showMoreMenu && moreMenuItems.length > 0}
                items={moreMenuItems}
                onClose={() => setShowMoreMenu(false)}
              />
            </div>
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
                    {displayNameFromThread(
                      activeThread,
                      session?.account_email,
                    )}
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
                    {hasHtmlPreview(message) ? (
                      <EmailHtmlPreview message={message} />
                    ) : (
                      <div className="message-plain-body">
                        {message.body || "No preview available."}
                      </div>
                    )}
                  </article>
                ))}
              </div>

              <div className="reply-panel">
                <div className="compose-mode-row">
                  <strong>
                    {composeMode === "reply"
                      ? "Reply"
                      : composeMode === "reply_all"
                        ? "Reply all"
                        : "Forward"}
                  </strong>
                </div>
                {composeMode === "forward" ? (
                  <div className="compose-recipient-grid">
                    <input
                      value={forwardTo}
                      onChange={(event) => setForwardTo(event.target.value)}
                      placeholder="To"
                      aria-label="Forward recipients"
                    />
                    <input
                      value={forwardCc}
                      onChange={(event) => setForwardCc(event.target.value)}
                      placeholder="Cc"
                      aria-label="Forward cc recipients"
                    />
                    <input
                      value={forwardBcc}
                      onChange={(event) => setForwardBcc(event.target.value)}
                      placeholder="Bcc"
                      aria-label="Forward bcc recipients"
                    />
                  </div>
                ) : null}
                <textarea
                  ref={composerRef}
                  value={composeBody}
                  onChange={(event) => setComposeBody(event.target.value)}
                  placeholder={
                    composeMode === "forward"
                      ? "Add a note before forwarding..."
                      : `Reply ${displayNameFromThread(activeThread, session?.account_email)}...`
                  }
                />
                <div className="reply-actions">
                  <span className="muted">
                    {composeMode === "forward"
                      ? "Forwarding sends a new Gmail message with the latest message quoted."
                      : "Replies stay in the current Gmail thread."}
                  </span>
                  <button
                    className="send-button"
                    onClick={() => void sendCompose()}
                    type="button"
                    disabled={sendingCompose}
                  >
                    {sendingCompose ? "Sending..." : "Send"}
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

      <ConfirmDialog
        open={confirmState !== null}
        title={confirmState?.title ?? ""}
        body={confirmState?.body ?? ""}
        confirmLabel={confirmState?.confirmLabel ?? "Confirm"}
        busy={actionInFlight !== null}
        onClose={() => setConfirmState(null)}
        onConfirm={() => {
          if (confirmState) {
            void runThreadAction(confirmState.action);
          }
        }}
      />
    </>
  );
}
