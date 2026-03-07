import { AuthView } from "@inboxos/features/auth/auth-view";
import { redirectIfAuthenticated } from "@inboxos/app/routes/auth-guard";

export async function AuthPage() {
  await redirectIfAuthenticated();
  return <AuthView />;
}
