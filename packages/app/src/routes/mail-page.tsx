import { cookies } from "next/headers";

import { SERVER_API_BASE } from "@inboxos/config/web";
import { MailWorkspace } from "@inboxos/features/mail/mail-workspace";
import { AuthSessionResponse, ThreadSummaryPage } from "@inboxos/types";

import { redirectIfUnauthenticated } from "./auth-guard";

type MailPageProps = {
  searchParams?: {
    thread?: string | string[];
  };
};

async function serverRequest<T>(path: string): Promise<T> {
  const cookieStore = cookies();
  const response = await fetch(`${SERVER_API_BASE}${path}`, {
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

async function serverRequestOrNull<T>(path: string): Promise<T | null> {
  try {
    return await serverRequest<T>(path);
  } catch {
    return null;
  }
}

export async function MailPage({ searchParams }: MailPageProps) {
  await redirectIfUnauthenticated();

  const selectedParam = searchParams?.thread;
  const initialThreadId = Array.isArray(selectedParam)
    ? selectedParam[0]
    : selectedParam;

  const initialSession =
    await serverRequest<AuthSessionResponse>("/auth/session");
  const initialThreadPage = await serverRequestOrNull<ThreadSummaryPage>(
    "/gmail/threads?page_size=20",
  );

  return (
    <MailWorkspace
      initialSession={initialSession}
      initialThreadPage={initialThreadPage}
      initialThreadId={initialThreadId ?? null}
    />
  );
}
