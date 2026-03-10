import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const ALLOWED_TOP_LEVEL_ROUTES = new Set([
  "accounts",
  "auth",
  "calendar",
  "gmail",
  "tasks",
]);

const HOP_BY_HOP_HEADERS = new Set([
  "connection",
  "content-length",
  "host",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
]);

function resolveGatewayOrigin(): string {
  const configuredOrigin = process.env.API_GATEWAY_ORIGIN?.trim();
  if (configuredOrigin) {
    return configuredOrigin.replace(/\/+$/, "");
  }

  if (process.env.NODE_ENV !== "production") {
    return "http://localhost:8000";
  }

  throw new Error("API_GATEWAY_ORIGIN is not configured.");
}

function buildUpstreamUrl(
  pathSegments: string[],
  search: string,
): URL | NextResponse {
  if (
    pathSegments.length === 0 ||
    !ALLOWED_TOP_LEVEL_ROUTES.has(pathSegments[0] ?? "")
  ) {
    return NextResponse.json({ detail: "Not found." }, { status: 404 });
  }

  const encodedPath = pathSegments.map((segment) =>
    encodeURIComponent(segment),
  );
  return new URL(
    `/${encodedPath.join("/")}${search}`,
    `${resolveGatewayOrigin()}/`,
  );
}

function copyRequestHeaders(request: NextRequest): Headers {
  const headers = new Headers();
  for (const [key, value] of request.headers) {
    if (HOP_BY_HOP_HEADERS.has(key.toLowerCase())) {
      continue;
    }
    headers.set(key, value);
  }

  const forwardedHost = request.headers.get("host");
  if (forwardedHost) {
    headers.set("x-forwarded-host", forwardedHost);
  }

  headers.set("x-forwarded-proto", request.nextUrl.protocol.replace(":", ""));

  return headers;
}

function copyResponseHeaders(upstream: Response): Headers {
  const headers = new Headers();
  for (const [key, value] of upstream.headers) {
    if (HOP_BY_HOP_HEADERS.has(key.toLowerCase()) || key === "set-cookie") {
      continue;
    }
    headers.set(key, value);
  }

  const getSetCookie = (
    upstream.headers as Headers & {
      getSetCookie?: () => string[];
    }
  ).getSetCookie;
  if (getSetCookie) {
    for (const value of getSetCookie.call(upstream.headers)) {
      headers.append("set-cookie", value);
    }
  } else {
    const setCookie = upstream.headers.get("set-cookie");
    if (setCookie) {
      headers.append("set-cookie", setCookie);
    }
  }

  return headers;
}

async function forward(
  method: "GET" | "POST" | "DELETE",
  request: NextRequest,
  pathSegments: string[],
): Promise<NextResponse> {
  let upstreamUrl: URL | NextResponse;
  try {
    upstreamUrl = buildUpstreamUrl(pathSegments, request.nextUrl.search);
  } catch (error) {
    const message =
      error instanceof Error ? error.message : "Gateway configuration error.";
    return NextResponse.json({ detail: message }, { status: 500 });
  }

  if (upstreamUrl instanceof NextResponse) {
    return upstreamUrl;
  }

  const body =
    method === "GET"
      ? undefined
      : await request.arrayBuffer().then((value) => {
          return value.byteLength > 0 ? value : undefined;
        });

  let upstream: Response;
  try {
    upstream = await fetch(upstreamUrl, {
      method,
      headers: copyRequestHeaders(request),
      body,
      cache: "no-store",
      redirect: "manual",
    });
  } catch (error) {
    const message =
      error instanceof Error ? error.message : "Gateway request failed.";
    return NextResponse.json({ detail: message }, { status: 502 });
  }

  const responseHeaders = copyResponseHeaders(upstream);
  const responseBody =
    upstream.status === 204 || upstream.status === 304
      ? null
      : await upstream.arrayBuffer();

  return new NextResponse(responseBody, {
    status: upstream.status,
    headers: responseHeaders,
  });
}

type GatewayRouteContext = {
  params: Promise<{
    path: string[];
  }>;
};

export async function GET(request: NextRequest, context: GatewayRouteContext) {
  const { path } = await context.params;
  return forward("GET", request, path);
}

export async function POST(request: NextRequest, context: GatewayRouteContext) {
  const { path } = await context.params;
  return forward("POST", request, path);
}

export async function DELETE(
  request: NextRequest,
  context: GatewayRouteContext,
) {
  const { path } = await context.params;
  return forward("DELETE", request, path);
}
