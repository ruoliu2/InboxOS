from __future__ import annotations

import base64
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from email.message import EmailMessage
from email.utils import parseaddr
from functools import partial
from html import unescape
from typing import Any
from urllib.parse import urlencode

import httpx

from app.core.config import Settings
from app.schemas.calendar import CalendarEvent, CreateCalendarEventRequest
from app.schemas.common import ActionState
from app.schemas.thread import (
    ComposeMode,
    ComposeThreadRequest,
    MailboxKey,
    ThreadDetail,
    ThreadMessage,
    ThreadSummary,
    ThreadSummaryPage,
)

GOOGLE_AUTH_BASE = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"
GMAIL_API_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"
CALENDAR_API_BASE = "https://www.googleapis.com/calendar/v3/calendars/primary"


class GoogleAPIError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        upstream_status_code: int,
        app_status_code: int = 502,
    ) -> None:
        super().__init__(message)
        self.upstream_status_code = upstream_status_code
        self.app_status_code = app_status_code


@dataclass
class GoogleTokenBundle:
    access_token: str
    refresh_token: str | None
    scope: str | None
    expires_at: datetime | None


@dataclass
class GoogleUserProfile:
    email: str
    name: str | None
    picture: str | None


@dataclass
class GmailComposeResult:
    thread: ThreadDetail
    sent_message: ThreadMessage


@dataclass
class GmailThreadActionResult:
    thread_id: str
    thread: ThreadDetail | None
    deleted: bool = False


class GoogleWorkspaceClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def build_authorization_url(self, state: str) -> str:
        if not self.settings.google_client_id or not self.settings.google_client_secret:
            raise RuntimeError("Google OAuth is not configured on the API.")

        query = urlencode(
            {
                "client_id": self.settings.google_client_id,
                "redirect_uri": self.settings.google_redirect_uri,
                "response_type": "code",
                "scope": " ".join(
                    [
                        "openid",
                        "email",
                        "profile",
                        "https://mail.google.com/",
                        "https://www.googleapis.com/auth/gmail.send",
                        "https://www.googleapis.com/auth/calendar.events",
                    ]
                ),
                "access_type": "offline",
                "include_granted_scopes": "true",
                "prompt": "consent",
                "state": state,
            }
        )
        return f"{GOOGLE_AUTH_BASE}?{query}"

    def exchange_code_for_tokens(self, code: str) -> GoogleTokenBundle:
        payload = self._post_form(
            GOOGLE_TOKEN_URL,
            {
                "client_id": self.settings.google_client_id,
                "client_secret": self.settings.google_client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": self.settings.google_redirect_uri,
            },
        )
        return self._parse_token_bundle(payload)

    def refresh_access_token(self, refresh_token: str) -> GoogleTokenBundle:
        payload = self._post_form(
            GOOGLE_TOKEN_URL,
            {
                "client_id": self.settings.google_client_id,
                "client_secret": self.settings.google_client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
        )
        payload["refresh_token"] = payload.get("refresh_token") or refresh_token
        return self._parse_token_bundle(payload)

    def get_user_profile(self, access_token: str) -> GoogleUserProfile:
        payload = self._request(
            "GET",
            GOOGLE_USERINFO_URL,
            access_token=access_token,
        )
        email = str(payload.get("email") or "").strip()
        if not email:
            raise RuntimeError("Google profile response did not include an email.")
        return GoogleUserProfile(
            email=email,
            name=str(payload.get("name") or "").strip() or None,
            picture=str(payload.get("picture") or "").strip() or None,
        )

    def list_gmail_threads(
        self,
        access_token: str,
        *,
        max_results: int = 20,
        page_token: str | None = None,
        mailbox: MailboxKey = MailboxKey.INBOX,
        unread_only: bool = False,
        query: str | None = None,
    ) -> ThreadSummaryPage:
        params: dict[str, str] = {
            "maxResults": str(max_results),
            "includeSpamTrash": (
                "true" if mailbox in (MailboxKey.TRASH, MailboxKey.JUNK) else "false"
            ),
        }
        label_id = self._gmail_label_for_mailbox(mailbox)
        if label_id is not None:
            params["labelIds"] = label_id
        if page_token:
            params["pageToken"] = page_token
        if effective_query := self._compose_thread_query(mailbox, query, unread_only):
            params["q"] = effective_query

        payload = self._request(
            "GET",
            f"{GMAIL_API_BASE}/threads",
            access_token=access_token,
            params=params,
        )
        next_page_token = str(payload.get("nextPageToken") or "").strip() or None
        total_count = self._parse_result_size_estimate(payload)
        thread_ids = [
            str(item.get("id") or "").strip()
            for item in payload.get("threads", [])
            if str(item.get("id") or "").strip()
        ]
        if not thread_ids:
            return ThreadSummaryPage(
                next_page_token=next_page_token,
                has_more=next_page_token is not None,
                total_count=total_count,
            )

        fetch_summary = partial(self.get_gmail_thread_summary, access_token)
        with ThreadPoolExecutor(max_workers=min(6, len(thread_ids))) as executor:
            threads = list(executor.map(fetch_summary, thread_ids))

        return ThreadSummaryPage(
            threads=threads,
            next_page_token=next_page_token,
            has_more=next_page_token is not None,
            total_count=total_count,
        )

    def get_gmail_thread_summary(
        self,
        access_token: str,
        thread_id: str,
    ) -> ThreadSummary:
        payload = self._get_gmail_thread_summary_payload(access_token, thread_id)
        return self._parse_thread_summary(payload)

    def get_gmail_thread(self, access_token: str, thread_id: str) -> ThreadDetail:
        payload = self._get_gmail_thread_payload(access_token, thread_id)
        return self._parse_thread(payload)

    def compose_gmail_thread(
        self,
        access_token: str,
        *,
        account_email: str,
        thread_id: str,
        payload: ComposeThreadRequest,
    ) -> GmailComposeResult:
        thread_payload = self._get_gmail_thread_payload(access_token, thread_id)
        raw_messages = thread_payload.get("messages", [])
        if not raw_messages:
            raise RuntimeError("Cannot reply to an empty Gmail thread.")

        latest_message = raw_messages[-1]
        headers = self._headers_map(
            latest_message.get("payload", {}).get("headers", [])
        )
        message = EmailMessage()

        if payload.mode == ComposeMode.REPLY:
            recipient = self._resolve_reply_recipient(
                raw_messages,
                account_email=account_email,
            )
            recipients = [recipient] if recipient else []
            cc_recipients: list[str] = []
            subject = self._prefix_subject(headers.get("subject"), "Re:")
            message_body = payload.body.strip()
            if not message_body:
                raise RuntimeError("Reply body must not be empty.")
            self._apply_thread_headers(message, headers)
        elif payload.mode == ComposeMode.REPLY_ALL:
            recipients, cc_recipients = self._reply_all_recipients(
                headers,
                account_email,
            )
            if not recipients and not cc_recipients:
                raise RuntimeError("Unable to determine Gmail reply-all recipients.")
            subject = self._prefix_subject(headers.get("subject"), "Re:")
            message_body = payload.body.strip()
            if not message_body:
                raise RuntimeError("Reply body must not be empty.")
            self._apply_thread_headers(message, headers)
        else:
            recipients = payload.to
            cc_recipients = payload.cc
            subject = self._prefix_subject(headers.get("subject"), "Fwd:")
            message_body = self._build_forward_body(
                payload.body, headers, latest_message
            )

        if not recipients:
            raise RuntimeError("Unable to determine Gmail message recipients.")

        message["To"] = ", ".join(recipients)
        if cc_recipients:
            message["Cc"] = ", ".join(cc_recipients)
        if payload.bcc:
            message["Bcc"] = ", ".join(payload.bcc)
        message["Subject"] = subject
        message.set_content(message_body)
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8").rstrip("=")

        send_payload = {
            "raw": raw,
        }
        if payload.mode in (ComposeMode.REPLY, ComposeMode.REPLY_ALL):
            send_payload["threadId"] = thread_id

        self._request(
            "POST",
            f"{GMAIL_API_BASE}/messages/send",
            access_token=access_token,
            json=send_payload,
        )

        refetched_thread = self.get_gmail_thread(access_token, thread_id)
        return GmailComposeResult(
            thread=refetched_thread,
            sent_message=refetched_thread.messages[-1],
        )

    def send_gmail_reply(
        self,
        access_token: str,
        *,
        account_email: str,
        thread_id: str,
        body: str,
    ) -> ThreadDetail:
        result = self.compose_gmail_thread(
            access_token,
            account_email=account_email,
            thread_id=thread_id,
            payload=ComposeThreadRequest(mode=ComposeMode.REPLY, body=body),
        )
        return result.thread

    def apply_gmail_thread_action(
        self,
        access_token: str,
        *,
        thread_id: str,
        action: str,
    ) -> GmailThreadActionResult:
        if action == "archive":
            self._modify_gmail_thread(
                access_token,
                thread_id,
                add_label_ids=[],
                remove_label_ids=["INBOX"],
            )
            return GmailThreadActionResult(
                thread_id=thread_id,
                thread=self.get_gmail_thread(access_token, thread_id),
            )

        if action == "junk":
            self._modify_gmail_thread(
                access_token,
                thread_id,
                add_label_ids=["SPAM"],
                remove_label_ids=["INBOX"],
            )
            return GmailThreadActionResult(
                thread_id=thread_id,
                thread=self.get_gmail_thread(access_token, thread_id),
            )

        if action == "trash":
            payload = self._request(
                "POST",
                f"{GMAIL_API_BASE}/threads/{thread_id}/trash",
                access_token=access_token,
            )
            return GmailThreadActionResult(
                thread_id=thread_id,
                thread=self._parse_thread(payload),
            )

        if action == "restore":
            payload = self._get_gmail_thread_payload(access_token, thread_id)
            labels = self._thread_label_ids(payload.get("messages", []))
            if "TRASH" in labels:
                self._request(
                    "POST",
                    f"{GMAIL_API_BASE}/threads/{thread_id}/untrash",
                    access_token=access_token,
                )

            if "SPAM" in labels:
                self._modify_gmail_thread(
                    access_token,
                    thread_id,
                    add_label_ids=["INBOX"],
                    remove_label_ids=["SPAM"],
                )

            return GmailThreadActionResult(
                thread_id=thread_id,
                thread=self.get_gmail_thread(access_token, thread_id),
            )

        if action == "delete":
            self._request(
                "DELETE",
                f"{GMAIL_API_BASE}/threads/{thread_id}",
                access_token=access_token,
            )
            return GmailThreadActionResult(
                thread_id=thread_id,
                thread=None,
                deleted=True,
            )

        raise RuntimeError(f"Unsupported Gmail thread action: {action}")

    def list_calendar_events(
        self,
        access_token: str,
        *,
        time_min: datetime,
        time_max: datetime,
        max_results: int = 250,
    ) -> list[CalendarEvent]:
        payload = self._request(
            "GET",
            f"{CALENDAR_API_BASE}/events",
            access_token=access_token,
            params={
                "singleEvents": "true",
                "orderBy": "startTime",
                "timeMin": self._to_rfc3339(time_min),
                "timeMax": self._to_rfc3339(time_max),
                "maxResults": str(max_results),
            },
        )
        events = [
            self._parse_calendar_event(item)
            for item in payload.get("items", [])
            if item.get("status") != "cancelled"
        ]
        events.sort(key=lambda item: item.starts_at)
        return events

    def create_calendar_event(
        self,
        access_token: str,
        payload: CreateCalendarEventRequest,
    ) -> CalendarEvent:
        request_payload: dict[str, Any] = {
            "summary": payload.title,
            "description": payload.description,
            "location": payload.location,
        }
        if payload.is_all_day:
            request_payload["start"] = {"date": payload.starts_at.date().isoformat()}
            request_payload["end"] = {
                "date": (payload.ends_at.date() + timedelta(days=1)).isoformat()
            }
        else:
            request_payload["start"] = {"dateTime": self._to_rfc3339(payload.starts_at)}
            request_payload["end"] = {"dateTime": self._to_rfc3339(payload.ends_at)}

        created = self._request(
            "POST",
            f"{CALENDAR_API_BASE}/events",
            access_token=access_token,
            json=request_payload,
        )
        return self._parse_calendar_event(created)

    def delete_calendar_event(self, access_token: str, event_id: str) -> None:
        self._request(
            "DELETE",
            f"{CALENDAR_API_BASE}/events/{event_id}",
            access_token=access_token,
        )

    def _post_form(self, url: str, payload: dict[str, str | None]) -> dict[str, Any]:
        return self._request(
            "POST",
            url,
            data={key: value for key, value in payload.items() if value is not None},
        )

    def _get_gmail_thread_payload(
        self,
        access_token: str,
        thread_id: str,
    ) -> dict[str, Any]:
        return self._request(
            "GET",
            f"{GMAIL_API_BASE}/threads/{thread_id}",
            access_token=access_token,
            params={"format": "full"},
        )

    def _get_gmail_thread_summary_payload(
        self,
        access_token: str,
        thread_id: str,
    ) -> dict[str, Any]:
        return self._request(
            "GET",
            f"{GMAIL_API_BASE}/threads/{thread_id}",
            access_token=access_token,
            params={"format": "metadata"},
        )

    def _request(
        self,
        method: str,
        url: str,
        *,
        access_token: str | None = None,
        params: dict[str, str] | None = None,
        data: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        headers: dict[str, str] = {}
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"

        with httpx.Client(timeout=20.0) as client:
            response = client.request(
                method,
                url,
                headers=headers,
                params=params,
                data=data,
                json=json,
            )

        if response.is_success:
            if response.status_code == 204 or not response.content:
                return {}
            return response.json()

        payload: dict[str, Any] | None = None
        try:
            parsed = response.json()
        except ValueError:
            parsed = None
        if isinstance(parsed, dict):
            payload = parsed

        raise self._build_api_error(
            upstream_status_code=response.status_code,
            fallback_detail=response.text.strip() or response.reason_phrase,
            payload=payload,
        )

    def _parse_token_bundle(self, payload: dict[str, Any]) -> GoogleTokenBundle:
        access_token = str(payload.get("access_token") or "").strip()
        if not access_token:
            raise RuntimeError("Google token response did not include an access token.")

        expires_in = payload.get("expires_in")
        expires_at: datetime | None = None
        if isinstance(expires_in, int | float):
            expires_at = datetime.now(UTC) + timedelta(seconds=int(expires_in))

        refresh_token = str(payload.get("refresh_token") or "").strip() or None
        scope = str(payload.get("scope") or "").strip() or None
        return GoogleTokenBundle(
            access_token=access_token,
            refresh_token=refresh_token,
            scope=scope,
            expires_at=expires_at,
        )

    def _parse_thread(self, payload: dict[str, Any]) -> ThreadDetail:
        raw_messages = payload.get("messages", [])
        messages = [self._parse_message(item) for item in raw_messages]
        messages.sort(key=lambda item: item.sent_at)

        participants = self._collect_participants(raw_messages)
        subject = self._thread_subject(raw_messages)
        snippet = str(payload.get("snippet") or "").strip()
        if not snippet and messages:
            snippet = messages[-1].body.replace("\n", " ").strip()

        unread = any("UNREAD" in (item.get("labelIds") or []) for item in raw_messages)
        return ThreadDetail(
            id=str(payload.get("id") or ""),
            subject=subject or "(no subject)",
            snippet=snippet[:240],
            participants=participants or ["unknown@example.com"],
            last_message_at=messages[-1].sent_at if messages else datetime.now(UTC),
            action_states=[ActionState.TO_REPLY] if unread else [ActionState.FYI],
            messages=messages,
            analysis=None,
        )

    def _parse_thread_summary(self, payload: dict[str, Any]) -> ThreadSummary:
        raw_messages = payload.get("messages", [])
        participants = self._collect_participants(raw_messages)
        subject = self._thread_subject(raw_messages)
        snippet = str(payload.get("snippet") or "").strip()
        unread = any("UNREAD" in (item.get("labelIds") or []) for item in raw_messages)

        return ThreadSummary(
            id=str(payload.get("id") or ""),
            subject=subject or "(no subject)",
            snippet=snippet[:240],
            participants=participants or ["unknown@example.com"],
            last_message_at=self._latest_message_timestamp(raw_messages),
            action_states=[ActionState.TO_REPLY] if unread else [ActionState.FYI],
        )

    def _parse_message(self, payload: dict[str, Any]) -> ThreadMessage:
        headers = self._headers_map(payload.get("payload", {}).get("headers", []))
        sender = headers.get("from") or "unknown@example.com"
        body = self._extract_message_body(payload.get("payload", {}))
        if not body:
            body = str(payload.get("snippet") or "").strip()

        sent_at = self._parse_gmail_datetime(payload.get("internalDate"))
        if sent_at is None:
            sent_at = datetime.now(UTC)

        return ThreadMessage(
            id=str(payload.get("id") or ""),
            sender=sender,
            sent_at=sent_at,
            body=body,
        )

    def _parse_calendar_event(self, payload: dict[str, Any]) -> CalendarEvent:
        start_raw = payload.get("start", {})
        end_raw = payload.get("end", {})

        is_all_day = "date" in start_raw
        starts_at = self._parse_calendar_datetime(start_raw)
        ends_at = self._parse_calendar_datetime(end_raw)

        return CalendarEvent(
            id=str(payload.get("id") or ""),
            title=str(payload.get("summary") or "").strip() or "(untitled event)",
            starts_at=starts_at,
            ends_at=ends_at,
            location=str(payload.get("location") or "").strip() or None,
            description=str(payload.get("description") or "").strip() or None,
            is_all_day=is_all_day,
            html_link=str(payload.get("htmlLink") or "").strip() or None,
            can_delete=not bool(payload.get("locked")),
        )

    def _headers_map(self, headers: list[dict[str, Any]]) -> dict[str, str]:
        values: dict[str, str] = {}
        for header in headers:
            name = str(header.get("name") or "").strip().lower()
            value = str(header.get("value") or "").strip()
            if name and value and name not in values:
                values[name] = value
        return values

    def _resolve_reply_recipient(
        self,
        messages: list[dict[str, Any]],
        *,
        account_email: str,
    ) -> str | None:
        normalized_account = account_email.strip().lower()
        for item in reversed(messages):
            headers = self._headers_map(item.get("payload", {}).get("headers", []))
            for header_name in ("reply-to", "from"):
                candidate = parseaddr(headers.get(header_name) or "")[1].strip()
                if candidate and candidate.lower() != normalized_account:
                    return candidate
        return None

    def _parse_result_size_estimate(self, payload: dict[str, Any]) -> int | None:
        raw_value = payload.get("resultSizeEstimate")
        if raw_value is None:
            return None
        try:
            return int(raw_value)
        except (TypeError, ValueError):
            return None

    def _thread_subject(self, messages: list[dict[str, Any]]) -> str:
        for item in messages:
            headers = self._headers_map(item.get("payload", {}).get("headers", []))
            subject = headers.get("subject")
            if subject:
                return subject
        return ""

    def _collect_participants(self, messages: list[dict[str, Any]]) -> list[str]:
        participants: list[str] = []
        seen: set[str] = set()
        for item in messages:
            headers = self._headers_map(item.get("payload", {}).get("headers", []))
            for key in ("from", "to", "cc"):
                for value in headers.get(key, "").split(","):
                    email = parseaddr(value.strip())[1].lower()
                    if email and email not in seen:
                        seen.add(email)
                        participants.append(email)
        return participants

    def _thread_label_ids(self, messages: list[dict[str, Any]]) -> set[str]:
        label_ids: set[str] = set()
        for item in messages:
            for label_id in item.get("labelIds", []) or []:
                normalized = str(label_id).strip()
                if normalized:
                    label_ids.add(normalized)
        return label_ids

    def _gmail_label_for_mailbox(self, mailbox: MailboxKey) -> str | None:
        return {
            MailboxKey.INBOX: "INBOX",
            MailboxKey.SENT: "SENT",
            MailboxKey.TRASH: "TRASH",
            MailboxKey.JUNK: "SPAM",
        }.get(mailbox)

    def _compose_thread_query(
        self,
        mailbox: MailboxKey,
        query: str | None,
        unread_only: bool,
    ) -> str | None:
        fragments: list[str] = []
        if mailbox == MailboxKey.ARCHIVE:
            fragments.append(
                "-label:inbox -label:sent -label:drafts -label:spam -label:trash"
            )
        if unread_only:
            fragments.append("is:unread")
        if query and query.strip():
            fragments.append(query.strip())
        combined = " ".join(fragment for fragment in fragments if fragment)
        return combined or None

    def _modify_gmail_thread(
        self,
        access_token: str,
        thread_id: str,
        *,
        add_label_ids: list[str],
        remove_label_ids: list[str],
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"{GMAIL_API_BASE}/threads/{thread_id}/modify",
            access_token=access_token,
            json={
                "addLabelIds": add_label_ids,
                "removeLabelIds": remove_label_ids,
            },
        )

    def _apply_thread_headers(
        self, message: EmailMessage, headers: dict[str, str]
    ) -> None:
        message_id = headers.get("message-id")
        references = headers.get("references")
        if message_id:
            message["In-Reply-To"] = message_id
        if references and message_id:
            message["References"] = f"{references} {message_id}"
        elif references:
            message["References"] = references
        elif message_id:
            message["References"] = message_id

    def _reply_all_recipients(
        self,
        headers: dict[str, str],
        account_email: str,
    ) -> tuple[list[str], list[str]]:
        current_account = account_email.strip().lower()
        primary = (
            parseaddr(headers.get("reply-to") or "")[1]
            or parseaddr(headers.get("from") or "")[1]
        )
        to_recipients = self._dedupe_recipients(
            [primary, *self._parse_recipient_header(headers.get("to"))],
            current_account,
        )
        seen = {item.lower() for item in to_recipients}
        cc_recipients = [
            recipient
            for recipient in self._parse_recipient_header(headers.get("cc"))
            if recipient.lower() not in seen and recipient.lower() != current_account
        ]
        return to_recipients, cc_recipients

    def _parse_recipient_header(self, value: str | None) -> list[str]:
        recipients: list[str] = []
        for candidate in (value or "").split(","):
            email = parseaddr(candidate.strip())[1].lower()
            if email:
                recipients.append(email)
        return recipients

    def _dedupe_recipients(
        self, recipients: list[str], current_account: str
    ) -> list[str]:
        values: list[str] = []
        seen: set[str] = set()
        for recipient in recipients:
            normalized = recipient.strip().lower()
            if not normalized or normalized == current_account or normalized in seen:
                continue
            seen.add(normalized)
            values.append(normalized)
        return values

    def _build_forward_body(
        self,
        body: str,
        headers: dict[str, str],
        latest_message: dict[str, Any],
    ) -> str:
        original_message = self._parse_message(latest_message)
        fragments = []
        if body.strip():
            fragments.append(body.strip())
            fragments.append("")
        fragments.extend(
            [
                "---------- Forwarded message ---------",
                f"From: {headers.get('from') or 'unknown@example.com'}",
                f"Date: {original_message.sent_at.isoformat()}",
                f"Subject: {headers.get('subject') or '(no subject)'}",
                f"To: {headers.get('to') or '(unknown recipient)'}",
            ]
        )
        if headers.get("cc"):
            fragments.append(f"Cc: {headers['cc']}")
        fragments.append("")
        fragments.append(original_message.body or "(No message body)")
        return "\n".join(fragments).strip()

    def _prefix_subject(self, subject: str | None, prefix: str) -> str:
        normalized_subject = (subject or "(no subject)").strip() or "(no subject)"
        if normalized_subject.lower().startswith(prefix.lower()):
            return normalized_subject
        return f"{prefix} {normalized_subject}"

    def _latest_message_timestamp(self, messages: list[dict[str, Any]]) -> datetime:
        timestamps = [
            parsed
            for item in messages
            if (parsed := self._parse_gmail_datetime(item.get("internalDate")))
            is not None
        ]
        if not timestamps:
            return datetime.now(UTC)
        return max(timestamps)

    def _extract_message_body(self, payload: dict[str, Any]) -> str:
        plain = self._find_body_part(payload, "text/plain")
        if plain:
            return plain

        html = self._find_body_part(payload, "text/html")
        if html:
            text = re.sub(r"<br\s*/?>", "\n", html, flags=re.IGNORECASE)
            text = re.sub(r"</(p|div|li|tr|h[1-6])>", "\n", text, flags=re.IGNORECASE)
            text = re.sub(r"<[^>]+>", "", text)
            text = unescape(text)
            text = re.sub(r"\n{3,}", "\n\n", text)
            return text.strip()

        return ""

    def _find_body_part(self, payload: dict[str, Any], mime_type: str) -> str:
        current_mime = str(payload.get("mimeType") or "")
        if current_mime == mime_type:
            encoded = str(payload.get("body", {}).get("data") or "")
            decoded = self._decode_base64url(encoded)
            if decoded:
                return decoded.strip()

        for part in payload.get("parts", []) or []:
            found = self._find_body_part(part, mime_type)
            if found:
                return found

        return ""

    def _decode_base64url(self, value: str) -> str:
        if not value:
            return ""
        padded = value + "=" * (-len(value) % 4)
        decoded = base64.urlsafe_b64decode(padded.encode("utf-8"))
        return decoded.decode("utf-8", errors="replace")

    def _parse_gmail_datetime(self, value: Any) -> datetime | None:
        if value is None:
            return None
        try:
            milliseconds = int(str(value))
        except ValueError:
            return None
        return datetime.fromtimestamp(milliseconds / 1000, tz=UTC)

    def _parse_calendar_datetime(self, payload: dict[str, Any]) -> datetime:
        date_time_value = str(payload.get("dateTime") or "").strip()
        if date_time_value:
            parsed = datetime.fromisoformat(date_time_value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)

        date_value = str(payload.get("date") or "").strip()
        parsed_date = date.fromisoformat(date_value)
        return datetime.combine(parsed_date, time.min, tzinfo=UTC)

    def _to_rfc3339(self, value: datetime) -> str:
        normalized = value if value.tzinfo else value.replace(tzinfo=UTC)
        return normalized.astimezone(UTC).isoformat().replace("+00:00", "Z")

    def _build_api_error(
        self,
        *,
        upstream_status_code: int,
        fallback_detail: str,
        payload: dict[str, Any] | None,
    ) -> GoogleAPIError:
        service_disabled = self._service_disabled_error(
            upstream_status_code=upstream_status_code,
            payload=payload,
        )
        if service_disabled is not None:
            return service_disabled

        detail = self._google_error_message(payload) or fallback_detail
        app_status_code = 404 if upstream_status_code == 404 else 502
        return GoogleAPIError(
            f"Google API {upstream_status_code}: {detail}",
            upstream_status_code=upstream_status_code,
            app_status_code=app_status_code,
        )

    def _service_disabled_error(
        self,
        *,
        upstream_status_code: int,
        payload: dict[str, Any] | None,
    ) -> GoogleAPIError | None:
        if not payload:
            return None

        details = payload.get("error", {}).get("details", [])
        if not isinstance(details, list):
            return None

        for item in details:
            if not isinstance(item, dict):
                continue
            if item.get("@type") != "type.googleapis.com/google.rpc.ErrorInfo":
                continue
            if str(item.get("reason") or "").strip() != "SERVICE_DISABLED":
                continue

            metadata = item.get("metadata", {})
            if not isinstance(metadata, dict):
                metadata = {}

            service_title = str(
                metadata.get("serviceTitle") or metadata.get("service") or "Google API"
            ).strip()
            project = str(
                metadata.get("containerInfo") or metadata.get("consumer") or ""
            ).strip()
            if project.startswith("projects/"):
                project = project.removeprefix("projects/")
            activation_url = str(metadata.get("activationUrl") or "").strip()

            fragments = [
                (
                    f"{service_title} is disabled for Google project {project}."
                    if project
                    else f"{service_title} is disabled for this Google project."
                )
            ]
            if activation_url:
                fragments.append(f"Enable it at {activation_url}.")
            fragments.append(
                "Wait a few minutes for Google to apply the change, then retry."
            )

            return GoogleAPIError(
                " ".join(fragments),
                upstream_status_code=upstream_status_code,
                app_status_code=503,
            )

        return None

    def _google_error_message(self, payload: dict[str, Any] | None) -> str | None:
        if not payload:
            return None

        error = payload.get("error")
        if not isinstance(error, dict):
            return None

        message = str(error.get("message") or "").strip()
        return message or None
