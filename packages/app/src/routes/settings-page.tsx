import { SettingsView } from "@inboxos/features/settings/settings-view";

import { redirectIfUnauthenticated } from "./auth-guard";

export async function SettingsPage() {
  await redirectIfUnauthenticated();

  return <SettingsView />;
}
