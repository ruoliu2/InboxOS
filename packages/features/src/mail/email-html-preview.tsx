"use client";

import { useEffect, useRef, useState } from "react";

import { ThreadInlineAsset, ThreadMessage } from "@inboxos/types";

const PREVIEW_CSP =
  "default-src 'none'; img-src https: data: blob:; media-src https: data: blob:; font-src https: data:; style-src 'unsafe-inline' https:; script-src 'none'; connect-src 'none'; frame-src 'none'; object-src 'none'; form-action 'none'; base-uri 'none'";

const URL_ATTRIBUTES = new Set([
  "action",
  "formaction",
  "href",
  "poster",
  "src",
  "xlink:href",
]);

function normalizeContentId(value: string): string {
  return value
    .trim()
    .replace(/^<+|>+$/g, "")
    .toLowerCase();
}

function replaceCidReferences(
  html: string,
  inlineAssets: ThreadInlineAsset[],
): string {
  if (inlineAssets.length === 0) {
    return html;
  }

  const assetMap = new Map(
    inlineAssets.map((asset) => [
      normalizeContentId(asset.content_id),
      asset.data_url,
    ]),
  );

  return html.replace(/cid:\s*<?([^"'()\s>]+)>?/gi, (match, contentId) => {
    return assetMap.get(normalizeContentId(contentId)) ?? match;
  });
}

function escapeHtmlAttribute(value: string): string {
  return value.replace(/&/g, "&amp;").replace(/"/g, "&quot;");
}

function hasExplicitFontStyling(document: Document): boolean {
  if (
    document.querySelector('[face], [style*="font-family"], [style*="font:"]')
  ) {
    return true;
  }

  return Array.from(document.querySelectorAll("style")).some((element) =>
    /font-family\s*:/i.test(element.textContent ?? ""),
  );
}

function sanitizeHtmlDocument(resolvedHtml: string): string {
  const parser = new DOMParser();
  const document = parser.parseFromString(resolvedHtml, "text/html");

  document
    .querySelectorAll(
      "script, iframe, frame, frameset, object, embed, portal, base",
    )
    .forEach((node) => node.remove());

  document.querySelectorAll("meta").forEach((node) => {
    const httpEquiv = node.getAttribute("http-equiv")?.trim().toLowerCase();
    if (httpEquiv === "refresh") {
      node.remove();
    }
  });

  document.querySelectorAll("*").forEach((element) => {
    for (const attribute of Array.from(element.attributes)) {
      const attributeName = attribute.name.toLowerCase();
      const attributeValue = attribute.value.trim();
      if (attributeName.startsWith("on") || attributeName === "srcdoc") {
        element.removeAttribute(attribute.name);
        continue;
      }

      if (
        URL_ATTRIBUTES.has(attributeName) &&
        attributeValue.toLowerCase().startsWith("javascript:")
      ) {
        element.removeAttribute(attribute.name);
      }
    }

    if (element.tagName.toLowerCase() === "a") {
      element.setAttribute("target", "_blank");
      element.setAttribute("rel", "noopener noreferrer nofollow");
    }
  });

  const defaultBodyFont = hasExplicitFontStyling(document)
    ? ""
    : ' font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, "Noto Sans", "Apple Color Emoji", "Segoe UI Emoji", "Segoe UI Symbol", sans-serif;';
  const previewStyles = [
    "html, body { margin: 0; padding: 0; background: transparent; }",
    `body { color: #111827; overflow-wrap: anywhere; font-size: 13px; line-height: 1.45;${defaultBodyFont} }`,
    "img, video { max-width: 100%; height: auto; }",
    "table { max-width: 100%; }",
    "pre { white-space: pre-wrap; }",
    "blockquote { margin-left: 0; padding-left: 12px; border-left: 3px solid #d1d5db; color: #3f3f46; }",
  ].join("\n");

  return [
    "<!DOCTYPE html>",
    "<html>",
    "<head>",
    '<meta charset="utf-8">',
    `<meta http-equiv="Content-Security-Policy" content="${escapeHtmlAttribute(PREVIEW_CSP)}">`,
    '<base target="_blank">',
    document.head.innerHTML,
    `<style>${previewStyles}</style>`,
    "</head>",
    "<body>",
    document.body.innerHTML,
    "</body>",
    "</html>",
  ].join("");
}

type EmailHtmlPreviewProps = {
  message: ThreadMessage;
};

export function EmailHtmlPreview({ message }: EmailHtmlPreviewProps) {
  const iframeRef = useRef<HTMLIFrameElement | null>(null);
  const resizeObserverRef = useRef<ResizeObserver | null>(null);
  const [frameHeight, setFrameHeight] = useState(72);
  const [srcDoc, setSrcDoc] = useState<string | null>(null);

  useEffect(() => {
    return () => {
      resizeObserverRef.current?.disconnect();
      resizeObserverRef.current = null;
    };
  }, []);

  useEffect(() => {
    const rawHtml = message.body_html?.trim();
    if (!rawHtml) {
      setSrcDoc(null);
      return;
    }

    const resolvedHtml = replaceCidReferences(rawHtml, message.inline_assets);
    setSrcDoc(sanitizeHtmlDocument(resolvedHtml));
  }, [message.body_html, message.inline_assets]);

  useEffect(() => {
    setFrameHeight(72);
    resizeObserverRef.current?.disconnect();
    resizeObserverRef.current = null;
  }, [srcDoc]);

  if (!srcDoc) {
    return <div className="message-plain-body">{message.body}</div>;
  }

  function syncHeight() {
    const document = iframeRef.current?.contentDocument;
    if (!document) {
      return;
    }

    const nextHeight = Math.max(
      document.documentElement.scrollHeight,
      document.body.scrollHeight,
      72,
    );
    setFrameHeight(nextHeight);
  }

  function handleLoad() {
    resizeObserverRef.current?.disconnect();
    resizeObserverRef.current = null;

    const document = iframeRef.current?.contentDocument;
    if (!document) {
      return;
    }

    syncHeight();

    if (typeof ResizeObserver === "undefined") {
      return;
    }

    const resizeObserver = new ResizeObserver(() => {
      syncHeight();
    });

    resizeObserver.observe(document.documentElement);
    resizeObserver.observe(document.body);
    resizeObserverRef.current = resizeObserver;
  }

  return (
    <div className="message-html-preview">
      <iframe
        ref={iframeRef}
        title={`HTML preview for ${message.sender}`}
        className="message-html-frame"
        sandbox="allow-same-origin allow-popups allow-popups-to-escape-sandbox"
        referrerPolicy="no-referrer"
        scrolling="no"
        srcDoc={srcDoc}
        onLoad={handleLoad}
        style={{ height: `${frameHeight}px` }}
      />
    </div>
  );
}
