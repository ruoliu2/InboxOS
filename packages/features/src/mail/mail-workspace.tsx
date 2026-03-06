"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertCircle,
  Archive,
  ArchiveX,
  ChevronDown,
  Clock,
  Forward,
  Inbox,
  MessagesSquare,
  MoreVertical,
  Reply,
  ReplyAll,
  Search,
  Send,
  ShoppingCart,
  Trash2,
  Triangle,
  Users2,
} from "lucide-react";

import { api } from "@inboxos/lib/api";
import { formatDate } from "@inboxos/lib/format";
import {
  findMockThreadDetail,
  mockThreadSummaries,
} from "@inboxos/lib/mock-data";
import { ThreadDetail, ThreadSummary } from "@inboxos/types";

type ListTab = "all" | "unread";

type MailWorkspaceProps = {
  initialThreadId?: string | null;
};

const primaryFolders = [
  { key: "inbox", label: "Inbox", icon: Inbox },
  { key: "sent", label: "Sent", icon: Send },
  { key: "junk", label: "Junk", icon: ArchiveX },
  { key: "trash", label: "Trash", icon: Trash2 },
  { key: "archive", label: "Archive", icon: Archive },
] as const;

const socialFolders = [
  { key: "social", label: "Social", count: 972, icon: Users2 },
  { key: "updates", label: "Updates", count: 342, icon: AlertCircle },
  { key: "forums", label: "Forums", count: 128, icon: MessagesSquare },
  { key: "shopping", label: "Shopping", count: 8, icon: ShoppingCart },
  { key: "promotions", label: "Promotions", count: 21, icon: Archive },
] as const;

function isUnread(thread: ThreadSummary): boolean {
  return thread.action_states.some((state) => state !== "fyi");
}

function displayNameFromThread(thread: ThreadSummary): string {
  const email =
    thread.participants.find((value) => value.includes("@")) ??
    "unknown@example.com";
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
    return `${diffDays} day${diffDays === 1 ? "" : "s"} ago`;
  }
  return `${diffMonths} month${diffMonths === 1 ? "" : "s"} ago`;
}

function labelsFromThread(thread: ThreadSummary): string[] {
  const labels: string[] = [];

  if (thread.action_states.includes("task")) {
    labels.push("work");
  }
  if (
    thread.action_states.includes("to_reply") ||
    thread.action_states.includes("to_follow_up")
  ) {
    labels.push("important");
  }
  if (thread.action_states.includes("fyi")) {
    labels.push("personal");
  }

  return labels.length ? labels : ["work"];
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

function sortThreadsByRecent(threads: ThreadSummary[]): ThreadSummary[] {
  return [...threads].sort(
    (left, right) =>
      new Date(right.last_message_at).getTime() -
      new Date(left.last_message_at).getTime(),
  );
}

export function MailWorkspace({ initialThreadId }: MailWorkspaceProps) {
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
  const [loadingThread, setLoadingThread] = useState(false);
  const [sendingReply, setSendingReply] = useState(false);
  const [isDemoMode, setIsDemoMode] = useState(false);
  const [activePrimaryFolder, setActivePrimaryFolder] =
    useState<(typeof primaryFolders)[number]["key"]>("inbox");

  const applyUpdatedThread = useCallback((updatedThread: ThreadDetail) => {
    setSelectedThread(updatedThread);
    setThreads((current) => {
      const nextSummary = toThreadSummary(updatedThread);
      const existing = current.some((thread) => thread.id === updatedThread.id);
      const nextThreads = existing
        ? current.map((thread) =>
            thread.id === updatedThread.id ? nextSummary : thread,
          )
        : [nextSummary, ...current];
      return sortThreadsByRecent(nextThreads);
    });
  }, []);

  const loadThreads = useCallback(async () => {
    setLoadingList(true);
    setError(null);
    setNotice(null);

    try {
      const data = await api.getThreads();
      if (data.length === 0) {
        setThreads(mockThreadSummaries);
        setIsDemoMode(true);
        setNotice("API returned no threads. Showing demo mailbox data.");
      } else {
        setThreads(sortThreadsByRecent(data));
        setIsDemoMode(false);
      }
    } catch {
      setThreads(mockThreadSummaries);
      setIsDemoMode(true);
      setNotice("API unavailable. Showing demo mailbox data from docs.");
    } finally {
      setLoadingList(false);
    }
  }, []);

  const loadThread = useCallback(
    async (threadId: string) => {
      setLoadingThread(true);
      setError(null);

      if (isDemoMode) {
        const mock = findMockThreadDetail(threadId);
        setSelectedThread(mock);
        setLoadingThread(false);
        return;
      }

      try {
        const data = await api.getThread(threadId);
        setSelectedThread(data);
      } catch (loadError) {
        const fallback = findMockThreadDetail(threadId);
        if (fallback) {
          setSelectedThread(fallback);
          setNotice("Thread detail fallback enabled for preview.");
        } else {
          setError((loadError as Error).message);
          setSelectedThread(null);
        }
      } finally {
        setLoadingThread(false);
      }
    },
    [isDemoMode],
  );

  useEffect(() => {
    void loadThreads();
  }, [loadThreads]);

  useEffect(() => {
    if (!threads.length) {
      setSelectedThreadId(null);
      return;
    }

    setSelectedThreadId((current) => {
      if (current && threads.some((thread) => thread.id === current)) {
        return current;
      }
      if (
        initialThreadId &&
        threads.some((thread) => thread.id === initialThreadId)
      ) {
        return initialThreadId;
      }
      return threads[0].id;
    });
  }, [initialThreadId, threads]);

  useEffect(() => {
    if (!selectedThreadId) {
      setSelectedThread(null);
      return;
    }

    void loadThread(selectedThreadId);
  }, [loadThread, selectedThreadId]);

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
    if (!selectedThreadId || !selectedThread) {
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

    if (isDemoMode) {
      const sentAt = new Date().toISOString();
      const updatedThread: ThreadDetail = {
        ...selectedThread,
        snippet: body.replace(/\s+/g, " ").slice(0, 160),
        last_message_at: sentAt,
        action_states: ["fyi"],
        messages: [
          ...selectedThread.messages,
          {
            id: `mock_msg_${Date.now()}`,
            sender: "you@example.com",
            sent_at: sentAt,
            body,
          },
        ],
      };
      applyUpdatedThread(updatedThread);
      setReplyText("");
      setMuteThread(false);
      setNotice(
        muteThread
          ? "Reply sent. Thread muted in demo mode."
          : "Reply sent in demo mode.",
      );
      setSendingReply(false);
      return;
    }

    try {
      const result = await api.replyToThread(selectedThreadId, {
        body,
        mute_thread: muteThread,
      });
      applyUpdatedThread(result.thread);
      setReplyText("");
      setMuteThread(false);
      setNotice(result.muted ? "Reply sent. Thread muted." : "Reply sent.");
    } catch (sendError) {
      setError((sendError as Error).message);
    } finally {
      setSendingReply(false);
    }
  }

  return (
    <main className="mail-shell panel-surface">
      <aside className="mail-left-nav">
        <div className="mail-account-select">
          <span className="account-logo" aria-hidden>
            <Triangle size={11} />
          </span>
          <span>Alicia Koch</span>
          <span className="account-caret" aria-hidden>
            <ChevronDown size={14} />
          </span>
        </div>

        <div className="mail-folder-group">
          {primaryFolders.map((folder) => {
            const count =
              folder.key === "inbox"
                ? threads.length
                : folder.key === "junk"
                  ? 23
                  : 0;
            return (
              <button
                key={folder.key}
                className={`folder-row ${activePrimaryFolder === folder.key ? "active" : ""}`.trim()}
                onClick={() => setActivePrimaryFolder(folder.key)}
                type="button"
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

        <div className="mail-folder-group secondary">
          {socialFolders.map((folder) => (
            <button key={folder.key} className="folder-row" type="button">
              <span className="folder-label">
                <folder.icon size={15} />
                {folder.label}
              </span>
              <span className="folder-count">{folder.count}</span>
            </button>
          ))}
        </div>

        {isDemoMode ? <p className="folder-note">Demo mode</p> : null}
      </aside>

      <section className="mail-center-list">
        <div className="list-topbar">
          <h1>Inbox</h1>
          <div className="list-tabs">
            <button
              className={listTab === "all" ? "active" : ""}
              onClick={() => setListTab("all")}
            >
              All mail
            </button>
            <button
              className={listTab === "unread" ? "active" : ""}
              onClick={() => setListTab("unread")}
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
              placeholder="Search"
              aria-label="Search mails"
            />
          </div>
        </div>

        {notice ? <p className="status inline-status">{notice}</p> : null}
        {error ? <p className="status error inline-status">{error}</p> : null}
        {loadingList ? <p className="list-empty">Loading mail...</p> : null}

        {!loadingList ? (
          <div className="mail-card-list">
            {visibleThreads.length === 0 ? (
              <p className="list-empty">No messages in this folder.</p>
            ) : null}
            {visibleThreads.map((thread) => {
              const name = displayNameFromThread(thread);
              const labels = labelsFromThread(thread);
              return (
                <button
                  key={thread.id}
                  className={`mail-card ${thread.id === selectedThreadId ? "active" : ""}`.trim()}
                  onClick={() => setSelectedThreadId(thread.id)}
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

        {!selectedThreadId ? (
          <p className="read-empty">No message selected</p>
        ) : null}
        {selectedThreadId && loadingThread ? (
          <p className="read-empty">Loading message...</p>
        ) : null}

        {selectedThread ? (
          <>
            <div className="read-header">
              <div className="avatar-circle">
                {initials(displayNameFromThread(selectedThread))}
              </div>
              <div>
                <strong>{displayNameFromThread(selectedThread)}</strong>
                <p>{selectedThread.subject}</p>
                <p>
                  Reply-To:{" "}
                  {selectedThread.participants.find((value) =>
                    value.includes("@"),
                  ) ?? "unknown@example.com"}
                </p>
              </div>
              <time>{formatDate(selectedThread.last_message_at)}</time>
            </div>

            <div className="read-body">
              {
                selectedThread.messages[selectedThread.messages.length - 1]
                  ?.body
              }
            </div>

            <div className="reply-panel">
              <textarea
                value={replyText}
                onChange={(event) => setReplyText(event.target.value)}
                placeholder={`Reply ${displayNameFromThread(selectedThread)}...`}
              />
              <div className="reply-actions">
                <label>
                  <input
                    type="checkbox"
                    checked={muteThread}
                    onChange={(event) => setMuteThread(event.target.checked)}
                  />
                  Mute this thread
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
      </section>
    </main>
  );
}
