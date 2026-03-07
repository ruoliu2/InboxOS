import { TasksView } from "@inboxos/features/tasks/tasks-view";
import { redirectIfUnauthenticated } from "@inboxos/app/routes/auth-guard";

export async function TasksPage() {
  await redirectIfUnauthenticated();
  return <TasksView />;
}
