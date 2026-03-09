"use client";

import {
  type CSSProperties,
  type ChangeEvent,
  type PointerEvent as ReactPointerEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  ArrowLeft,
  Archive,
  ArchiveX,
  ChevronDown,
  Clock,
  Forward,
  Inbox,
  LogOut,
  Mailbox,
  MoreVertical,
  PenSquare,
  Reply,
  ReplyAll,
  Search,
  Send,
  Trash2,
  Triangle,
} from "lucide-react";

import { ApiError, api } from "@inboxos/lib/api";
import { formatDate } from "@inboxos/lib/format";
import {
  AuthSessionResponse,
  ComposeMode,
  MailboxCounts,
  MailboxKey,
  ThreadActionName,
  ThreadDetail,
  ThreadListItem,
  ThreadMessage,
  ThreadSummary,
} from "@inboxos/types";
import { ConfirmDialog } from "@inboxos/ui/confirm-dialog";
import { OverflowMenu } from "@inboxos/ui/overflow-menu";

import { EmailHtmlPreview } from "./email-html-preview";
import {
  NewMessageAttachment,
  NewMessageComposer,
} from "./new-message-composer";

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

type ResizeTarget = "nav" | "list" | null;

const PAGE_SIZE = 20;
const HYDRATE_BATCH_SIZE = 8;
const DEFAULT_MAIL_NAV_WIDTH = 208;
const MAIL_RESIZER_WIDTH = 10;
const MIN_MAIL_NAV_WIDTH = 176;
const MAX_MAIL_NAV_WIDTH = 280;
const MIN_LIST_PANE_WIDTH = 280;
const DEFAULT_LIST_PANE_WIDTH = 328;
const MAX_LIST_PANE_WIDTH = 420;
const MIN_READ_PANE_WIDTH = 360;
const EMPTY_MAILBOX_COUNTS: MailboxCounts = {
  inbox: null,
  sent: null,
  archive: null,
  trash: null,
  junk: null,
};

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

function isReadyThread(
  thread: ThreadListItem | ThreadDetail,
): thread is ThreadSummary {
  return "state" in thread && thread.state === "ready";
}

function normalizedEmail(value: string | null | undefined): string | null {
  const normalized = value?.trim().toLowerCase();
  return normalized && normalized.includes("@") ? normalized : null;
}

function counterpartyEmailFromThread(
  thread: ThreadSummary | ThreadDetail,
  accountEmail?: string | null,
): string {
  const preferredRecipient = preferredComposeRecipientFromThread(
    thread,
    accountEmail,
  );
  if (preferredRecipient) {
    return preferredRecipient;
  }

  return "unknown@example.com";
}

function preferredComposeRecipientFromThread(
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
    ""
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
    state: "ready",
    id: thread.id,
    subject: thread.subject,
    snippet: thread.snippet,
    participants: thread.participants,
    last_message_at: thread.last_message_at,
    action_states: thread.action_states,
  };
}

function mergeThreadItems(
  current: ThreadListItem[],
  incoming: ThreadListItem[],
): ThreadListItem[] {
  if (incoming.length === 0) {
    return current;
  }

  const incomingById = new Map(incoming.map((thread) => [thread.id, thread]));
  const currentIds = new Set(current.map((thread) => thread.id));
  return [
    ...current.map((thread) => incomingById.get(thread.id) ?? thread),
    ...incoming.filter((thread) => !currentIds.has(thread.id)),
  ];
}

function mergeReadyThreads(
  current: ThreadListItem[],
  incoming: ThreadSummary[],
  position: "append" | "prepend" = "append",
): ThreadListItem[] {
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
    .split(/[;,]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function hasHtmlPreview(message: ThreadMessage): boolean {
  return Boolean(message.body_html?.trim());
}

function revokeAttachmentPreviews(attachments: NewMessageAttachment[]): void {
  for (const attachment of attachments) {
    URL.revokeObjectURL(attachment.previewUrl);
  }
}

function buildSkeletonRows(count = 6): ThreadListItem[] {
  return Array.from({ length: count }, (_, index) => ({
    state: "placeholder" as const,
    id: `skeleton-${index + 1}`,
  }));
}

export function MailWorkspace({ initialThreadId }: MailWorkspaceProps) {
  const [session, setSession] = useState<AuthSessionResponse | null>(null);
  const [sessionChecked, setSessionChecked] = useState(false);
  const [mailboxCounts, setMailboxCounts] =
    useState<MailboxCounts>(EMPTY_MAILBOX_COUNTS);
  const [threads, setThreads] = useState<ThreadListItem[]>([]);
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
  const [newMessageOpen, setNewMessageOpen] = useState(false);
  const [newMessageTo, setNewMessageTo] = useState("");
  const [newMessageSubject, setNewMessageSubject] = useState("");
  const [newMessageBody, setNewMessageBody] = useState("");
  const [newMessageAttachments, setNewMessageAttachments] = useState<
    NewMessageAttachment[]
  >([]);
  const [sendingNewMessage, setSendingNewMessage] = useState(false);
  const [newMessageMinimized, setNewMessageMinimized] = useState(false);
  const [newMessageMaximized, setNewMessageMaximized] = useState(false);
  const [scheduleMenuOpen, setScheduleMenuOpen] = useState(false);
  const [navPaneWidth, setNavPaneWidth] = useState(DEFAULT_MAIL_NAV_WIDTH);
  const [listPaneWidth, setListPaneWidth] = useState(DEFAULT_LIST_PANE_WIDTH);
  const threadRequestIdRef = useRef(0);
  const listRequestIdRef = useRef(0);
  const hydrationEpochRef = useRef(0);
  const hydratedIdsRef = useRef<Set<string>>(new Set());
  const hydratingIdsRef = useRef<Set<string>>(new Set());
  const composerRef = useRef<HTMLTextAreaElement | null>(null);
  const listScrollerRef = useRef<HTMLDivElement | null>(null);
  const loadMoreTriggerRef = useRef<HTMLDivElement | null>(null);
  const newMessageAttachmentsRef = useRef<NewMessageAttachment[]>([]);
  const mailShellRef = useRef<HTMLElement | null>(null);
  const navPaneWidthRef = useRef(DEFAULT_MAIL_NAV_WIDTH);
  const listPaneWidthRef = useRef(DEFAULT_LIST_PANE_WIDTH);
  const resizeTargetRef = useRef<ResizeTarget>(null);
  const resizePointerIdRef = useRef<number | null>(null);
  const resizeStartXRef = useRef(0);
  const resizeStartWidthRef = useRef(DEFAULT_LIST_PANE_WIDTH);

  const unreadOnly = listTab === "unread";
  const activeHeading = mailboxHeading(mailbox);
  const handleAuthError = useCallback((error: unknown): boolean => {
    if (error instanceof ApiError && error.status === 401) {
      window.location.href = "/auth";
      return true;
    }
    return false;
  }, []);
  const loadMailboxCounts = useCallback(async () => {
    if (!session?.authenticated) {
      return;
    }

    try {
      const counts = await api.getGmailMailboxCounts();
      setMailboxCounts(counts);
    } catch (loadError) {
      if (handleAuthError(loadError)) {
        return;
      }
      setMailboxCounts(EMPTY_MAILBOX_COUNTS);
    }
  }, [handleAuthError, session?.authenticated]);

  const resetHydration = useCallback(() => {
    hydrationEpochRef.current += 1;
    hydratingIdsRef.current.clear();
    hydratedIdsRef.current.clear();
  }, []);

  const hydrateThreadIds = useCallback(
    async (threadIds: string[]) => {
      const normalized = threadIds.filter((threadId) => {
        return (
          Boolean(threadId) &&
          !hydratedIdsRef.current.has(threadId) &&
          !hydratingIdsRef.current.has(threadId)
        );
      });
      if (normalized.length === 0) {
        return;
      }

      const requestId = hydrationEpochRef.current;
      normalized.forEach((threadId) => hydratingIdsRef.current.add(threadId));
      try {
        const response = await api.hydrateGmailThreads(normalized);
        if (requestId !== hydrationEpochRef.current) {
          return;
        }
        const readyThreads = Object.values(response.threads);
        readyThreads.forEach((thread) => hydratedIdsRef.current.add(thread.id));
        setThreads((current) => mergeReadyThreads(current, readyThreads));
      } catch (hydrateError) {
        if (handleAuthError(hydrateError)) {
          return;
        }
        if (requestId === hydrationEpochRef.current) {
          setError((hydrateError as Error).message);
        }
      } finally {
        normalized.forEach((threadId) =>
          hydratingIdsRef.current.delete(threadId),
        );
      }
    },
    [handleAuthError],
  );

  const loadInitialThreads = useCallback(async () => {
    if (!session?.authenticated) {
      return;
    }

    const requestId = listRequestIdRef.current + 1;
    listRequestIdRef.current = requestId;
    hydrationEpochRef.current += 1;
    hydratingIdsRef.current.clear();
    hydratedIdsRef.current.clear();
    setLoadingList(true);
    setError(null);
    setNotice(null);
    setThreads([]);
    setNextPageToken(null);
    setHasMore(false);

    try {
      const page = await api.getGmailThreads({
        page_size: PAGE_SIZE,
        q: searchQuery || undefined,
        mailbox,
        unread_only: unreadOnly,
      });
      if (requestId !== listRequestIdRef.current) {
        return;
      }
      setThreads(page.threads);
      setNextPageToken(page.next_page_token);
      setHasMore(page.has_more);
      page.threads.forEach((thread) => {
        if (thread.state === "ready") {
          hydratedIdsRef.current.add(thread.id);
        }
      });
    } catch (loadError) {
      if (handleAuthError(loadError)) {
        return;
      }
      if (requestId !== listRequestIdRef.current) {
        return;
      }
      setError((loadError as Error).message);
      setThreads([]);
      setNextPageToken(null);
      setHasMore(false);
    } finally {
      if (requestId === listRequestIdRef.current) {
        setLoadingList(false);
      }
    }
  }, [
    activeHeading,
    handleAuthError,
    mailbox,
    searchQuery,
    session?.authenticated,
    unreadOnly,
  ]);

  const loadMoreThreads = useCallback(async () => {
    if (
      !session?.authenticated ||
      !nextPageToken ||
      loadingList ||
      loadingMore
    ) {
      return;
    }

    const requestId = listRequestIdRef.current;
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
      if (requestId !== listRequestIdRef.current) {
        return;
      }
      setThreads((current) => mergeThreadItems(current, page.threads));
      setNextPageToken(page.next_page_token);
      setHasMore(page.has_more);
      page.threads.forEach((thread) => {
        if (thread.state === "ready") {
          hydratedIdsRef.current.add(thread.id);
        }
      });
    } catch (loadError) {
      if (handleAuthError(loadError)) {
        return;
      }
      if (requestId === listRequestIdRef.current) {
        setError((loadError as Error).message);
      }
    } finally {
      if (requestId === listRequestIdRef.current) {
        setLoadingMore(false);
      }
    }
  }, [
    loadingList,
    loadingMore,
    mailbox,
    nextPageToken,
    searchQuery,
    handleAuthError,
    session?.authenticated,
    unreadOnly,
  ]);

  const clearNewMessageComposer = useCallback(() => {
    setNewMessageOpen(false);
    setNewMessageMinimized(false);
    setNewMessageMaximized(false);
    setScheduleMenuOpen(false);
    setNewMessageTo("");
    setNewMessageSubject("");
    setNewMessageBody("");
    setNewMessageAttachments((current) => {
      revokeAttachmentPreviews(current);
      return [];
    });
  }, []);

  useEffect(() => {
    newMessageAttachmentsRef.current = newMessageAttachments;
  }, [newMessageAttachments]);

  useEffect(() => {
    return () => {
      revokeAttachmentPreviews(newMessageAttachmentsRef.current);
    };
  }, []);

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
          if (handleAuthError(sessionError)) {
            return;
          }
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
  }, [handleAuthError]);

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
    void loadMailboxCounts();
  }, [loadMailboxCounts, session?.authenticated, sessionChecked]);

  useEffect(() => {
    if (!sessionChecked || !session?.authenticated) {
      return;
    }

    setSelectedThreadId(null);
    setSelectedThread(null);
    setShowMoreMenu(false);
    resetHydration();
    void loadInitialThreads();
  }, [
    loadInitialThreads,
    mailbox,
    resetHydration,
    searchQuery,
    session?.authenticated,
    sessionChecked,
    unreadOnly,
  ]);

  useEffect(() => {
    const unresolved = threads
      .filter((thread) => thread.state === "placeholder")
      .slice(0, HYDRATE_BATCH_SIZE)
      .map((thread) => thread.id);
    if (unresolved.length === 0) {
      return;
    }
    void hydrateThreadIds(unresolved);
  }, [hydrateThreadIds, threads]);

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
          mergeReadyThreads(
            current,
            [toThreadSummary(data)],
            current.some((thread) => thread.id === data.id)
              ? "append"
              : "prepend",
          ),
        );
        hydratedIdsRef.current.add(data.id);
      })
      .catch((loadError) => {
        if (threadRequestIdRef.current !== requestId) {
          return;
        }
        if (handleAuthError(loadError)) {
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
  }, [handleAuthError, selectedThreadId]);

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
    session?.account_name ??
    session?.user?.display_name ??
    session?.account_email ??
    session?.user?.primary_email ??
    "Google account";
  const canSendNewMessage =
    parseRecipients(newMessageTo).length > 0 &&
    Boolean(newMessageSubject.trim()) &&
    !sendingNewMessage;

  useEffect(() => {
    navPaneWidthRef.current = navPaneWidth;
  }, [navPaneWidth]);

  useEffect(() => {
    listPaneWidthRef.current = listPaneWidth;
  }, [listPaneWidth]);

  const clampNavPaneWidth = useCallback(
    (nextWidth: number, listWidth = listPaneWidthRef.current): number => {
      const shellWidth = mailShellRef.current?.clientWidth ?? 0;
      const maxWidthFromShell =
        shellWidth > 0
          ? shellWidth -
            listWidth -
            MIN_READ_PANE_WIDTH -
            MAIL_RESIZER_WIDTH * 2
          : MAX_MAIL_NAV_WIDTH;
      const cappedMaxWidth = Math.min(MAX_MAIL_NAV_WIDTH, maxWidthFromShell);
      const safeMaxWidth = Math.max(MIN_MAIL_NAV_WIDTH, cappedMaxWidth);
      return Math.min(Math.max(nextWidth, MIN_MAIL_NAV_WIDTH), safeMaxWidth);
    },
    [],
  );

  const clampListPaneWidth = useCallback(
    (nextWidth: number, navWidth = navPaneWidthRef.current): number => {
      const shellWidth = mailShellRef.current?.clientWidth ?? 0;
      const maxWidthFromShell =
        shellWidth > 0
          ? shellWidth -
            navWidth -
            MIN_READ_PANE_WIDTH -
            MAIL_RESIZER_WIDTH * 2 -
            8
          : MAX_LIST_PANE_WIDTH;
      const cappedMaxWidth = Math.min(MAX_LIST_PANE_WIDTH, maxWidthFromShell);
      const safeMaxWidth = Math.max(MIN_LIST_PANE_WIDTH, cappedMaxWidth);
      return Math.min(Math.max(nextWidth, MIN_LIST_PANE_WIDTH), safeMaxWidth);
    },
    [],
  );

  const syncPaneWidths = useCallback(() => {
    const nextNavWidth = clampNavPaneWidth(
      navPaneWidthRef.current,
      listPaneWidthRef.current,
    );
    if (nextNavWidth !== navPaneWidthRef.current) {
      setNavPaneWidth(nextNavWidth);
    }
    const nextListWidth = clampListPaneWidth(
      listPaneWidthRef.current,
      nextNavWidth,
    );
    if (nextListWidth !== listPaneWidthRef.current) {
      setListPaneWidth(nextListWidth);
    }
  }, [clampListPaneWidth, clampNavPaneWidth]);

  const finishPaneResize = useCallback(() => {
    resizeTargetRef.current = null;
    resizePointerIdRef.current = null;
    document.body.classList.remove("mail-resizing");
  }, []);

  const startPaneResize = useCallback(
    (
      target: Exclude<ResizeTarget, null>,
      event: ReactPointerEvent<HTMLDivElement>,
    ) => {
      if (window.innerWidth <= 720) {
        return;
      }
      resizeTargetRef.current = target;
      resizePointerIdRef.current = event.pointerId;
      resizeStartXRef.current = event.clientX;
      resizeStartWidthRef.current =
        target === "nav" ? navPaneWidthRef.current : listPaneWidthRef.current;
      event.currentTarget.setPointerCapture(event.pointerId);
      document.body.classList.add("mail-resizing");
    },
    [],
  );

  const handlePaneResizeMove = useCallback(
    (event: ReactPointerEvent<HTMLDivElement>) => {
      if (resizePointerIdRef.current !== event.pointerId) {
        return;
      }
      const deltaX = event.clientX - resizeStartXRef.current;
      if (resizeTargetRef.current === "nav") {
        setNavPaneWidth(
          clampNavPaneWidth(resizeStartWidthRef.current + deltaX),
        );
        return;
      }
      if (resizeTargetRef.current === "list") {
        setListPaneWidth(
          clampListPaneWidth(resizeStartWidthRef.current + deltaX),
        );
      }
    },
    [clampListPaneWidth, clampNavPaneWidth],
  );

  const handlePaneResizeEnd = useCallback(
    (event?: ReactPointerEvent<HTMLDivElement>) => {
      if (event && resizePointerIdRef.current !== event.pointerId) {
        return;
      }
      finishPaneResize();
    },
    [finishPaneResize],
  );

  useEffect(() => {
    return () => {
      document.body.classList.remove("mail-resizing");
    };
  }, []);

  useEffect(() => {
    function syncPaneWidth() {
      syncPaneWidths();
    }

    window.addEventListener("resize", syncPaneWidth);
    return () => {
      window.removeEventListener("resize", syncPaneWidth);
    };
  }, [syncPaneWidths]);

  useEffect(() => {
    syncPaneWidths();
  }, [navPaneWidth, syncPaneWidths]);

  function focusComposer(mode: ComposeMode) {
    setComposeMode(mode);
    setNotice(null);
    setError(null);
    window.requestAnimationFrame(() => {
      composerRef.current?.focus();
    });
  }

  function openNewMessageComposer() {
    clearNewMessageComposer();
    setNewMessageTo(
      activeThread
        ? preferredComposeRecipientFromThread(
            activeThread,
            session?.account_email,
          )
        : "",
    );
    setNotice(null);
    setError(null);
    setNewMessageOpen(true);
  }

  function closeNewMessageComposer() {
    if (sendingNewMessage) {
      return;
    }
    clearNewMessageComposer();
  }

  function toggleNewMessageMinimized() {
    setScheduleMenuOpen(false);
    setNewMessageMaximized(false);
    setNewMessageMinimized((current) => !current);
  }

  function toggleNewMessageMaximized() {
    setScheduleMenuOpen(false);
    setNewMessageMaximized((current) => !current);
    setNewMessageMinimized(false);
  }

  function handleNewMessageAttachments(event: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(event.target.files ?? []);
    if (files.length === 0) {
      return;
    }

    const validFiles = files.filter((file) => file.type.startsWith("image/"));
    if (validFiles.length !== files.length) {
      setError(
        "Only image attachments are supported in the new message composer.",
      );
    }

    setNewMessageAttachments((current) => [
      ...current,
      ...validFiles.map((file, index) => ({
        id: `${file.name}-${file.lastModified}-${current.length + index}`,
        file,
        previewUrl: URL.createObjectURL(file),
      })),
    ]);
    event.target.value = "";
  }

  function removeNewMessageAttachment(attachmentId: string) {
    setNewMessageAttachments((current) => {
      const attachment = current.find((item) => item.id === attachmentId);
      if (attachment) {
        URL.revokeObjectURL(attachment.previewUrl);
      }
      return current.filter((item) => item.id !== attachmentId);
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
            mergeReadyThreads(
              current,
              [toThreadSummary(updatedThread)],
              "prepend",
            ),
          );
          hydratedIdsRef.current.add(updatedThread.id);
        }

        if (shouldClearSelection || result.deleted) {
          setSelectedThreadId(null);
          setSelectedThread(null);
        }

        await Promise.all([loadInitialThreads(), loadMailboxCounts()]);
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
        if (handleAuthError(actionError)) {
          return;
        }
        setError((actionError as Error).message);
      } finally {
        setActionInFlight(null);
        setConfirmState(null);
      }
    },
    [
      handleAuthError,
      loadInitialThreads,
      loadMailboxCounts,
      mailbox,
      selectedThreadId,
    ],
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
        mergeReadyThreads(current, [toThreadSummary(result.thread)], "prepend"),
      );
      hydratedIdsRef.current.add(result.thread.id);
      await loadMailboxCounts();
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
      if (handleAuthError(composeError)) {
        return;
      }
      setError((composeError as Error).message);
    } finally {
      setSendingCompose(false);
    }
  }

  async function sendNewMessage() {
    const recipients = parseRecipients(newMessageTo);
    if (recipients.length === 0 || !newMessageSubject.trim()) {
      return;
    }

    setSendingNewMessage(true);
    setNotice(null);
    setError(null);

    try {
      await api.sendGmailMessage({
        to: recipients,
        subject: newMessageSubject.trim(),
        body: newMessageBody,
        attachments: newMessageAttachments.map((attachment) => attachment.file),
      });
      await Promise.all([
        loadMailboxCounts(),
        mailbox === "sent" ? loadInitialThreads() : Promise.resolve(),
      ]);
      clearNewMessageComposer();
      setNotice("New email sent through Gmail.");
    } catch (sendError) {
      if (handleAuthError(sendError)) {
        return;
      }
      setError((sendError as Error).message);
    } finally {
      setSendingNewMessage(false);
    }
  }

  async function signOut() {
    try {
      await api.logout();
    } finally {
      setMailboxCounts(EMPTY_MAILBOX_COUNTS);
      window.location.href = "/auth";
    }
  }

  const listRows =
    threads.length === 0 && loadingList ? buildSkeletonRows() : threads;
  const emptyListCopy = searchQuery
    ? "No matching messages were found."
    : unreadOnly
      ? "No unread messages in this Gmail view."
      : "No messages in this Gmail view.";

  return (
    <>
      <main className="mail-page">
        <section
          ref={mailShellRef}
          className={`mail-shell ${selectedThreadId ? "thread-selected" : ""}`.trim()}
          style={
            {
              "--mail-nav-width": `${navPaneWidth}px`,
              "--mail-list-width": `${listPaneWidth}px`,
            } as CSSProperties
          }
        >
          <aside className="mail-left-nav panel-surface">
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
                const count = mailboxCounts[folder.key];
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
                    <span className="folder-count">
                      {count === null ? "" : count}
                    </span>
                  </button>
                );
              })}
            </div>

            <div className="mail-folder-group">
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

          <div
            className="mail-pane-resizer mail-pane-resizer-nav"
            role="separator"
            aria-label="Resize folders and inbox panes"
            aria-orientation="vertical"
            onPointerDown={(event) => startPaneResize("nav", event)}
            onPointerMove={handlePaneResizeMove}
            onPointerUp={handlePaneResizeEnd}
            onPointerCancel={handlePaneResizeEnd}
            onLostPointerCapture={handlePaneResizeEnd}
          />

          <section className="mail-center-list panel-surface">
            <div className="list-topbar">
              <div className="list-heading">
                <h2>{activeHeading}</h2>
              </div>
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
            {error ? (
              <p className="status error inline-status">{error}</p>
            ) : null}

            <div className="mail-card-list" ref={listScrollerRef}>
              {listRows.length === 0 && !loadingList && !error ? (
                <p className="list-empty">{emptyListCopy}</p>
              ) : null}
              {listRows.map((thread) => {
                const readyThread = isReadyThread(thread) ? thread : null;
                const name = readyThread
                  ? displayNameFromThread(readyThread, session?.account_email)
                  : "Loading thread";
                const labels = readyThread ? labelsFromThread(readyThread) : [];
                return (
                  <button
                    key={thread.id}
                    className={`mail-card ${thread.id === selectedThreadId ? "active" : ""} ${readyThread ? "" : "border-dashed border-[#d6dce6] text-[var(--muted)]"}`.trim()}
                    disabled={!readyThread && thread.id.startsWith("skeleton-")}
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
                    {readyThread ? (
                      <>
                        <div className="mail-card-row">
                          <strong>{name}</strong>
                          <span>
                            {relativeTime(readyThread.last_message_at)}
                          </span>
                        </div>
                        <p className="mail-card-subject">
                          {readyThread.subject}
                        </p>
                        <p className="mail-card-snippet">
                          {readyThread.snippet}
                        </p>
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
                      </>
                    ) : (
                      <div className="grid w-full gap-2.5" aria-hidden>
                        <div className="h-2.5 w-[46%] animate-pulse rounded-full bg-[#eef1f5]" />
                        <div className="h-2.5 w-[72%] animate-pulse rounded-full bg-[#eef1f5]" />
                        <div className="h-2.5 w-full animate-pulse rounded-full bg-[#eef1f5]" />
                        <div className="h-2.5 w-[64%] animate-pulse rounded-full bg-[#eef1f5]" />
                      </div>
                    )}
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
          </section>

          <div
            className="mail-pane-resizer mail-pane-resizer-list"
            role="separator"
            aria-label="Resize inbox and preview panes"
            aria-orientation="vertical"
            onPointerDown={(event) => startPaneResize("list", event)}
            onPointerMove={handlePaneResizeMove}
            onPointerUp={handlePaneResizeEnd}
            onPointerCancel={handlePaneResizeEnd}
            onLostPointerCapture={handlePaneResizeEnd}
          />

          <section className="mail-read-pane panel-surface">
            <div className="read-toolbar">
              <button
                type="button"
                aria-label="Back to thread list"
                className="thread-back-button"
                onClick={() => {
                  setSelectedThreadId(null);
                  setSelectedThread(null);
                  setLoadingThread(false);
                  setError(null);
                }}
              >
                <ArrowLeft size={15} />
              </button>
              <button
                type="button"
                aria-label="Compose new email"
                onClick={openNewMessageComposer}
              >
                <PenSquare size={15} />
              </button>
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
                      displayNameFromThread(
                        activeThread,
                        session?.account_email,
                      ),
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
                        : undefined
                    }
                  />
                  <div className="reply-actions">
                    {composeMode === "forward" ? (
                      <span className="muted">
                        Forwarding sends a new Gmail message with the latest
                        message quoted.
                      </span>
                    ) : (
                      <span />
                    )}
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

      <NewMessageComposer
        open={newMessageOpen}
        sending={sendingNewMessage}
        minimized={newMessageMinimized}
        maximized={newMessageMaximized}
        scheduleMenuOpen={scheduleMenuOpen}
        to={newMessageTo}
        subject={newMessageSubject}
        body={newMessageBody}
        attachments={newMessageAttachments}
        accountLabel={accountLabel}
        accountEmail={session?.account_email}
        canSend={canSendNewMessage}
        onOpenChange={(open) => {
          if (!open) {
            closeNewMessageComposer();
          }
        }}
        onToggleMinimized={toggleNewMessageMinimized}
        onToggleMaximized={toggleNewMessageMaximized}
        onScheduleMenuOpenChange={setScheduleMenuOpen}
        onToChange={setNewMessageTo}
        onSubjectChange={setNewMessageSubject}
        onBodyChange={setNewMessageBody}
        onAttachmentsChange={handleNewMessageAttachments}
        onRemoveAttachment={removeNewMessageAttachment}
        onSend={() => {
          void sendNewMessage();
        }}
        onScheduleAtEight={() => {
          setNotice("Send at 8:00 am is not available in gamma yet.");
        }}
      />
    </>
  );
}
