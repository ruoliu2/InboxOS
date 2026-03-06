export type ActionState = "to_reply" | "to_follow_up" | "task" | "fyi";
export type TaskStatus = "open" | "completed";

export type ThreadSummary = {
  id: string;
  subject: string;
  snippet: string;
  participants: string[];
  last_message_at: string;
  action_states: ActionState[];
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

export type CreateTaskRequest = {
  title: string;
  due_at?: string | null;
  thread_id?: string | null;
  category?: string | null;
};
