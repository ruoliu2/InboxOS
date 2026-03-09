import { TaskItem } from "@inboxos/types";

const baseDate = new Date("2026-03-05T16:00:00.000Z");

function hoursAgo(hours: number): string {
  return new Date(baseDate.getTime() - hours * 60 * 60 * 1000).toISOString();
}

function daysAgo(days: number): string {
  return new Date(
    baseDate.getTime() - days * 24 * 60 * 60 * 1000,
  ).toISOString();
}
export const mockTasks: TaskItem[] = [
  {
    id: "TASK-1001",
    title: "Reply to recruiter with resume and salary expectation",
    status: "open",
    due_at: hoursAgo(-24),
    linked_account_id: null,
    conversation_id: null,
    thread_id: "mock_thr_6",
    category: "deadline",
    origin: "manual",
    origin_key: null,
    deadline_source: "explicit",
    created_at: daysAgo(1),
    completed_at: null,
  },
  {
    id: "TASK-1002",
    title: "Follow up with Emily on budget discrepancy",
    status: "open",
    due_at: daysAgo(-2),
    linked_account_id: null,
    conversation_id: null,
    thread_id: "mock_thr_4",
    category: "follow-up",
    origin: "manual",
    origin_key: null,
    deadline_source: "explicit",
    created_at: daysAgo(2),
    completed_at: null,
  },
  {
    id: "TASK-1003",
    title: "Prepare talking points for project sync",
    status: "open",
    due_at: null,
    linked_account_id: null,
    conversation_id: null,
    thread_id: "mock_thr_1",
    category: "meeting",
    origin: "manual",
    origin_key: null,
    deadline_source: null,
    created_at: daysAgo(3),
    completed_at: null,
  },
  {
    id: "TASK-1004",
    title: "Review Alice feedback attachment",
    status: "completed",
    due_at: null,
    linked_account_id: null,
    conversation_id: null,
    thread_id: "mock_thr_2",
    category: "review",
    origin: "manual",
    origin_key: null,
    deadline_source: null,
    created_at: daysAgo(7),
    completed_at: daysAgo(5),
  },
];
