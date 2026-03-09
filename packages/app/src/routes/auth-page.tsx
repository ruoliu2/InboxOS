import { Suspense } from "react";

import { AuthView } from "@inboxos/features/auth/auth-view";

import { redirectIfAuthenticated } from "./auth-guard";

export async function AuthPage() {
  await redirectIfAuthenticated();

  return (
    <Suspense fallback={null}>
      <AuthView />
    </Suspense>
  );
}
