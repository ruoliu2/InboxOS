import { cookies } from "next/headers";

import { MailWorkspace } from "@inboxos/features/mail/mail-workspace";
import { AuthSessionResponse, ThreadSummaryPage } from "@inboxos/types";

import { redirectIfUnauthenticated } from "./auth-guard";

type MailPageProps = {
  searchParams?: {
    thread?: string | string[];
  };
};

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

async function serverRequest<T>(path: string): Promise<T> {
  const cookieStore = cookies();
  const response = await fetch(`${API_BASE}${path}`, {
    headers: {
      cookie: cookieStore.toString(),
    },
    cache: "no-store",
  });

  if (!response.ok) {
    throw new Error(`API ${response.status}`);
  }

  return (await response.json()) as T;
}

export async function MailPage({ searchParams }: MailPageProps) {
  await redirectIfUnauthenticated();

  const selectedParam = searchParams?.thread;
  const initialThreadId = Array.isArray(selectedParam)
    ? selectedParam[0]
    : selectedParam;

  const [initialSession, initialThreadPage] = await Promise.all([
    serverRequest<AuthSessionResponse>("/auth/session"),
    serverRequest<ThreadSummaryPage>("/gmail/threads?page_size=20"),
  ]);

  return (
    <MailWorkspace
      initialSession={initialSession}
      initialThreadPage={initialThreadPage}
      initialThreadId={initialThreadId ?? null}
    />
  );
}
