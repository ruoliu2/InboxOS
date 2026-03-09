import { API_BASE } from "@inboxos/config/web";
import {
  LinkedAccount,
  AuthSessionResponse,
  AuthStartResponse,
  CalendarEvent,
  ComposeThreadRequest,
  ComposeThreadResponse,
  CreateCalendarEventRequest,
  CreateTaskRequest,
  MailboxCounts,
  ReplyToThreadResponse,
  SendGmailMessageRequest,
  SendGmailMessageResponse,
  TaskItem,
  ThreadActionName,
  ThreadActionResponse,
  ThreadDetail,
  ThreadHydrateResponse,
  ThreadSummaryPage,
  MailboxKey,
} from "@inboxos/types";

export type SendGmailMessageInput = SendGmailMessageRequest & {
  attachments?: unknown[];
};

async function readErrorMessage(response: Response): Promise<string> {
  const body = await response.text();
  if (!body) {
    return `API ${response.status}`;
  }

  try {
    const payload = JSON.parse(body) as { detail?: unknown };
    if (typeof payload.detail === "string" && payload.detail.trim()) {
      return payload.detail;
    }
  } catch {
    // Fall back to the raw response body when the API did not return JSON.
  }

  return `API ${response.status}: ${body}`;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const isFormData =
    typeof FormData !== "undefined" && init?.body instanceof FormData;
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    credentials: "include",
    headers: {
      ...(!init?.body || isFormData
        ? {}
        : { "Content-Type": "application/json" }),
      ...(init?.headers ?? {}),
    },
    cache: "no-store",
  });

  if (response.status === 401) {
    if (typeof window !== "undefined") {
      window.location.href = "/auth";
    }
    throw new Error("Authentication required.");
  }

  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  if (response.status === 204) {
    return undefined as T;
  }

  const text = await response.text();
  return (text ? JSON.parse(text) : undefined) as T;
}

export const api = {
  startGoogleAuth: (redirectTo = "/mail") =>
    request<AuthStartResponse>(
      `/auth/google/start?redirect_to=${encodeURIComponent(redirectTo)}`,
    ),
  startAccountConnect: (provider: string, redirectTo = "/mail") =>
    request<AuthStartResponse>(
      `/accounts/${encodeURIComponent(provider)}/connect/start?redirect_to=${encodeURIComponent(redirectTo)}`,
      { method: "POST" },
    ),
  getAccounts: () => request<LinkedAccount[]>("/accounts"),
  activateAccount: (accountId: string) =>
    request<AuthSessionResponse>(`/accounts/${accountId}/activate`, {
      method: "POST",
    }),
  disconnectAccount: (accountId: string) =>
    request<void>(`/accounts/${accountId}/disconnect`, {
      method: "POST",
    }),
  getSession: () => request<AuthSessionResponse>("/auth/session"),
  logout: () => request<void>("/auth/logout", { method: "POST" }),
  getGmailMailboxCounts: () => request<MailboxCounts>("/gmail/mailbox-counts"),
  getGmailThreads: (options?: {
    page_token?: string | null;
    page_size?: number;
    q?: string;
    mailbox?: MailboxKey;
    unread_only?: boolean;
  }) => {
    const params = new URLSearchParams();
    if (options?.page_token) {
      params.set("page_token", options.page_token);
    }
    if (options?.page_size) {
      params.set("page_size", String(options.page_size));
    }
    if (options?.q) {
      params.set("q", options.q);
    }
    if (options?.mailbox) {
      params.set("mailbox", options.mailbox);
    }
    if (options?.unread_only) {
      params.set("unread_only", "true");
    }

    const query = params.toString();
    return request<ThreadSummaryPage>(
      query ? `/gmail/threads?${query}` : "/gmail/threads",
    );
  },
  getGmailThread: (threadId: string) =>
    request<ThreadDetail>(`/gmail/threads/${threadId}`),
  hydrateGmailThreads: (thread_ids: string[]) =>
    request<ThreadHydrateResponse>("/gmail/threads/hydrate", {
      method: "POST",
      body: JSON.stringify({ thread_ids }),
    }),
  replyToGmailThread: (
    threadId: string,
    payload: { body: string; mute_thread: boolean },
  ) =>
    request<ReplyToThreadResponse>(`/gmail/threads/${threadId}/reply`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  composeGmailThread: (threadId: string, payload: ComposeThreadRequest) =>
    request<ComposeThreadResponse>(`/gmail/threads/${threadId}/compose`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  sendGmailMessage: (payload: SendGmailMessageInput) => {
    const formData = new FormData();
    for (const recipient of payload.to) {
      formData.append("to", recipient);
    }
    formData.append("subject", payload.subject);
    formData.append("body", payload.body);
    for (const attachment of payload.attachments ?? []) {
      formData.append("attachments", attachment as never);
    }

    return request<SendGmailMessageResponse>("/gmail/messages/send", {
      method: "POST",
      body: formData,
    });
  },
  actOnGmailThread: (threadId: string, action: ThreadActionName) =>
    request<ThreadActionResponse>(`/gmail/threads/${threadId}/action`, {
      method: "POST",
      body: JSON.stringify({ action }),
    }),
  getCalendarEvents: (timeMin: string, timeMax: string) =>
    request<CalendarEvent[]>(
      `/calendar/events?time_min=${encodeURIComponent(timeMin)}&time_max=${encodeURIComponent(timeMax)}`,
    ),
  createCalendarEvent: (payload: CreateCalendarEventRequest) =>
    request<CalendarEvent>("/calendar/events", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  deleteCalendarEvent: (eventId: string) =>
    request<void>(`/calendar/events/${eventId}`, {
      method: "DELETE",
    }),
  getTasks: () => request<TaskItem[]>("/tasks"),
  createTask: (payload: CreateTaskRequest) =>
    request<TaskItem>("/tasks/create", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  completeTask: (taskId: string) =>
    request(`/tasks/${taskId}/complete`, {
      method: "POST",
    }),
};
