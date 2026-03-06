import { MailWorkspace } from "@inboxos/features/mail/mail-workspace";

type MailPageProps = {
  searchParams?: {
    thread?: string | string[];
  };
};

export function MailPage({ searchParams }: MailPageProps) {
  const selectedParam = searchParams?.thread;
  const initialThreadId = Array.isArray(selectedParam)
    ? selectedParam[0]
    : selectedParam;

  return <MailWorkspace initialThreadId={initialThreadId ?? null} />;
}
