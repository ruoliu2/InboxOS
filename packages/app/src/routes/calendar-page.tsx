import { CalendarWorkspace } from "@inboxos/features/calendar/calendar-workspace";
import { redirectIfUnauthenticated } from "@inboxos/app/routes/auth-guard";

export async function CalendarPage() {
  await redirectIfUnauthenticated();
  return <CalendarWorkspace />;
}
