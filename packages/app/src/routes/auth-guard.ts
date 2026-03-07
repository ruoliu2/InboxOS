import { cookies } from "next/headers";
import { redirect } from "next/navigation";

const SESSION_COOKIE_NAME =
  process.env.NEXT_PUBLIC_SESSION_COOKIE_NAME ?? "inboxos_session";
const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

type AuthSessionStatus = {
  authenticated: boolean;
};

async function getAuthSessionStatus(): Promise<AuthSessionStatus> {
  const cookieStore = cookies();
  const sessionCookie = cookieStore.get(SESSION_COOKIE_NAME)?.value;
  if (!sessionCookie) {
    return { authenticated: false };
  }

  try {
    const response = await fetch(`${API_BASE}/auth/session`, {
      headers: {
        cookie: cookieStore.toString(),
      },
      cache: "no-store",
    });

    if (!response.ok) {
      return { authenticated: false };
    }

    return (await response.json()) as AuthSessionStatus;
  } catch {
    return { authenticated: false };
  }
}

export async function redirectIfUnauthenticated() {
  const session = await getAuthSessionStatus();
  if (!session.authenticated) {
    redirect("/auth");
  }
}

export async function redirectIfAuthenticated() {
  const session = await getAuthSessionStatus();
  if (session.authenticated) {
    redirect("/mail");
  }
}
