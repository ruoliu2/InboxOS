export type ActionState = "to_reply" | "to_follow_up" | "task" | "fyi";
export type TaskStatus = "open" | "completed";
export type MailboxKey = "inbox" | "sent" | "archive" | "trash" | "junk";
export type ComposeMode = "reply" | "reply_all" | "forward";
export type ThreadActionName =
  | "archive"
  | "junk"
  | "trash"
  | "delete"
  | "restore";

export type ThreadSummary = {
  id: string;
  subject: string;
  snippet: string;
  participants: string[];
  last_message_at: string;
  action_states: ActionState[];
};

export type ThreadSummaryPage = {
  threads: ThreadSummary[];
  next_page_token: string | null;
  has_more: boolean;
};

export type ThreadMessage = {
  id: string;
  sender: string;
  sent_at: string;
  body: string;
};

export type ThreadAnalysis = {
  summary: string;
  action_items: string[];
  deadlines: string[];
  requested_items: string[];
  recommended_next_action: string;
  action_states: ActionState[];
  analyzed_at: string;
};

export type ThreadDetail = ThreadSummary & {
  messages: ThreadMessage[];
  analysis: ThreadAnalysis | null;
};

export type ReplyToThreadResponse = {
  thread: ThreadDetail;
  sent_message: ThreadMessage;
  muted: boolean;
};

export type ComposeThreadRequest = {
  mode: ComposeMode;
  body: string;
  to?: string[];
  cc?: string[];
  bcc?: string[];
};

export type ComposeThreadResponse = {
  thread: ThreadDetail;
  sent_message: ThreadMessage;
  mode: ComposeMode;
};

export type ThreadActionRequest = {
  action: ThreadActionName;
};

export type ThreadActionResponse = {
  thread_id: string;
  action: ThreadActionName;
  thread: ThreadDetail | null;
  deleted: boolean;
};

export type TaskItem = {
  id: string;
  title: string;
  status: TaskStatus;
  due_at: string | null;
  thread_id: string | null;
  category: string | null;
  created_at: string;
  completed_at: string | null;
};

export type SyncStartResponse = {
  sync_id: string;
  status: string;
  imported_threads: number;
  started_at: string;
};

export type AuthStartResponse = {
  provider: string;
  authorization_url: string;
  state: string;
};

export type AuthSessionResponse = {
  authenticated: boolean;
  provider: string | null;
  account_email: string | null;
  account_name: string | null;
  account_picture: string | null;
};

export type CalendarEvent = {
  id: string;
  title: string;
  starts_at: string;
  ends_at: string;
  location: string | null;
  description: string | null;
  is_all_day: boolean;
  html_link: string | null;
  can_delete: boolean;
};

export type CreateTaskRequest = {
  title: string;
  due_at?: string | null;
  thread_id?: string | null;
  category?: string | null;
};

export type CreateCalendarEventRequest = {
  title: string;
  starts_at: string;
  ends_at: string;
  is_all_day?: boolean;
  location?: string | null;
  description?: string | null;
};
