import { API_BASE } from "@inboxos/config/web";
import {
  AuthStartResponse,
  CreateTaskRequest,
  ReplyToThreadResponse,
  SyncStartResponse,
  TaskItem,
  ThreadDetail,
  ThreadSummary,
} from "@inboxos/types";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
    cache: "no-store",
  });

  if (!response.ok) {
    const body = await response.text();
    throw new Error(`API ${response.status}: ${body}`);
  }

  return response.json() as Promise<T>;
}

export const api = {
  startGoogleAuth: () => request<AuthStartResponse>("/auth/google/start"),
  startSync: () =>
    request<SyncStartResponse>("/sync/start", { method: "POST", body: "{}" }),
  getThreads: (actionState?: string) =>
    request<ThreadSummary[]>(
      actionState
        ? `/threads?action_state=${encodeURIComponent(actionState)}`
        : "/threads",
    ),
  getThread: (threadId: string) =>
    request<ThreadDetail>(`/threads/${threadId}`),
  analyzeThread: (threadId: string) =>
    request(`/threads/${threadId}/analyze`, { method: "POST" }),
  replyToThread: (
    threadId: string,
    payload: { body: string; mute_thread: boolean },
  ) =>
    request<ReplyToThreadResponse>(`/threads/${threadId}/reply`, {
      method: "POST",
      body: JSON.stringify(payload),
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
