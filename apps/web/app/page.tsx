import { cookies } from "next/headers";
import { redirect } from "next/navigation";

const SESSION_COOKIE_NAME =
  process.env.NEXT_PUBLIC_SESSION_COOKIE_NAME ?? "inboxos_session";

export default function Page() {
  if (cookies().get(SESSION_COOKIE_NAME)?.value) {
    redirect("/mail");
  }
  redirect("/auth");
}
