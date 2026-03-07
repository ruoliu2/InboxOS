import { MailWorkspace } from "@inboxos/features/mail/mail-workspace";
import { redirectIfUnauthenticated } from "@inboxos/app/routes/auth-guard";

type MailPageProps = {
  searchParams?: {
    thread?: string | string[];
  };
};

export async function MailPage({ searchParams }: MailPageProps) {
  await redirectIfUnauthenticated();
  const selectedParam = searchParams?.thread;
  const initialThreadId = Array.isArray(selectedParam)
    ? selectedParam[0]
    : selectedParam;

  return <MailWorkspace initialThreadId={initialThreadId ?? null} />;
}
