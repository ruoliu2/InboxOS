import { Suspense } from "react";

import { AuthView } from "@inboxos/features/auth/auth-view";

export function AuthPage() {
  return (
    <Suspense fallback={null}>
      <AuthView />
    </Suspense>
  );
}
