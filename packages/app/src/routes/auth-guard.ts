import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { SERVER_API_BASE } from "@inboxos/config/web";

const SESSION_COOKIE_NAME =
  process.env.NEXT_PUBLIC_SESSION_COOKIE_NAME ?? "inboxos_session";

type AuthSessionStatus = {
  authenticated: boolean;
  uncertain: boolean;
};

export function hasSessionCookie(): boolean {
  return Boolean(cookies().get(SESSION_COOKIE_NAME)?.value);
}

export async function getAuthSessionStatus(): Promise<AuthSessionStatus> {
  const cookieStore = cookies();
  const sessionCookie = cookieStore.get(SESSION_COOKIE_NAME)?.value;
  if (!sessionCookie) {
    return { authenticated: false, uncertain: false };
  }

  try {
    const response = await fetch(`${SERVER_API_BASE}/auth/session`, {
      headers: {
        cookie: cookieStore.toString(),
      },
      cache: "no-store",
    });

    if (!response.ok) {
      return {
        authenticated: false,
        uncertain: response.status >= 500,
      };
    }

    const session = (await response.json()) as { authenticated: boolean };
    return { authenticated: session.authenticated, uncertain: false };
  } catch {
    return { authenticated: false, uncertain: true };
  }
}

export async function redirectIfUnauthenticated() {
  const session = await getAuthSessionStatus();
  if (!session.authenticated && !session.uncertain) {
    redirect("/auth");
  }
}

export async function redirectIfAuthenticated() {
  const session = await getAuthSessionStatus();
  if (session.authenticated) {
    redirect("/mail");
  }
}
