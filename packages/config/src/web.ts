export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export const SERVER_API_BASE =
  process.env.INTERNAL_API_BASE_URL ?? process.env.API_BASE_URL ?? API_BASE;
