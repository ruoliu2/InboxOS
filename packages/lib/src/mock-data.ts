import { TaskItem, ThreadDetail, ThreadSummary } from "@inboxos/types";

const baseDate = new Date("2026-03-05T16:00:00.000Z");

function hoursAgo(hours: number): string {
  return new Date(baseDate.getTime() - hours * 60 * 60 * 1000).toISOString();
}

function daysAgo(days: number): string {
  return new Date(
    baseDate.getTime() - days * 24 * 60 * 60 * 1000,
  ).toISOString();
}

export const mockThreadDetails: ThreadDetail[] = [
  {
    id: "mock_thr_1",
    subject: "Meeting Tomorrow",
    snippet:
      "Hi, let's have a meeting tomorrow to discuss the project. I've been reviewing the project details...",
    participants: ["williamsmith@example.com", "you@example.com"],
    last_message_at: hoursAgo(3),
    action_states: ["to_reply"],
    analysis: null,
    messages: [
      {
        id: "mock_msg_1",
        sender: "williamsmith@example.com",
        sent_at: hoursAgo(3),
        body: "Hi, let's have a meeting tomorrow to discuss the project. I've been reviewing the project details and have some ideas I'd like to share. Please come prepared with questions. Best regards, William",
        body_html: null,
        inline_assets: [],
      },
    ],
  },
  {
    id: "mock_thr_2",
    subject: "Re: Project Update",
    snippet:
      "Thank you for the project update. It looks great! I've gone through the report and progress is impressive...",
    participants: ["alicesmith@example.com", "you@example.com"],
    last_message_at: hoursAgo(8),
    action_states: ["to_reply", "task"],
    analysis: null,
    messages: [
      {
        id: "mock_msg_2",
        sender: "alicesmith@example.com",
        sent_at: hoursAgo(8),
        body: "Thank you for the project update. It looks great! I've gone through the report, and the progress is impressive. I have a few minor suggestions in the attached doc. Let's discuss in our next meeting. Best regards, Alice",
        body_html: null,
        inline_assets: [],
      },
    ],
  },
  {
    id: "mock_thr_3",
    subject: "Weekend Plans",
    snippet:
      "Any plans for the weekend? I was thinking of going hiking in the nearby mountains...",
    participants: ["bobjohnson@example.com", "you@example.com"],
    last_message_at: daysAgo(5),
    action_states: ["fyi"],
    analysis: null,
    messages: [
      {
        id: "mock_msg_3",
        sender: "bobjohnson@example.com",
        sent_at: daysAgo(5),
        body: "Any plans for the weekend? I was thinking of going hiking in the nearby mountains. Let me know if you're interested.",
        body_html: null,
        inline_assets: [],
      },
    ],
  },
  {
    id: "mock_thr_4",
    subject: "Re: Question about Budget",
    snippet:
      "I have a question about the budget for the upcoming project. It seems like there's a discrepancy...",
    participants: ["emilydavis@example.com", "you@example.com"],
    last_message_at: daysAgo(9),
    action_states: ["to_follow_up", "task"],
    analysis: null,
    messages: [
      {
        id: "mock_msg_4",
        sender: "emilydavis@example.com",
        sent_at: daysAgo(9),
        body: "I have a question about the budget for the upcoming project. It seems like there is a discrepancy in resource allocation. Could we review this this week?",
        body_html: null,
        inline_assets: [],
      },
    ],
  },
  {
    id: "mock_thr_5",
    subject: "Important Announcement",
    snippet:
      "I have an important announcement to make during our team meeting. It pertains to a strategic shift...",
    participants: ["michaelwilson@example.com", "you@example.com"],
    last_message_at: daysAgo(12),
    action_states: ["fyi"],
    analysis: null,
    messages: [
      {
        id: "mock_msg_5",
        sender: "michaelwilson@example.com",
        sent_at: daysAgo(12),
        body: "I have an important announcement to make during our team meeting. It pertains to a strategic shift in our product launch approach.",
        body_html: null,
        inline_assets: [],
      },
    ],
  },
  {
    id: "mock_thr_6",
    subject: "Recruiter follow-up: personal information",
    snippet: "Please send your updated resume and expected salary by Friday.",
    participants: ["recruiter@acme.com", "you@example.com"],
    last_message_at: hoursAgo(20),
    action_states: ["to_reply", "task"],
    analysis: null,
    messages: [
      {
        id: "mock_msg_6",
        sender: "recruiter@acme.com",
        sent_at: hoursAgo(20),
        body: "Hi, can you share your updated resume and expected salary by Friday?",
        body_html: null,
        inline_assets: [],
      },
    ],
  },
];

export const mockThreadSummaries: ThreadSummary[] = mockThreadDetails.map(
  (thread) => ({
    id: thread.id,
    subject: thread.subject,
    snippet: thread.snippet,
    participants: thread.participants,
    last_message_at: thread.last_message_at,
    action_states: thread.action_states,
  }),
);

export function findMockThreadDetail(threadId: string): ThreadDetail | null {
  return mockThreadDetails.find((thread) => thread.id === threadId) ?? null;
}

export const mockTasks: TaskItem[] = [
  {
    id: "TASK-1001",
    title: "Reply to recruiter with resume and salary expectation",
    status: "open",
    due_at: hoursAgo(-24),
    thread_id: "mock_thr_6",
    category: "deadline",
    created_at: daysAgo(1),
    completed_at: null,
  },
  {
    id: "TASK-1002",
    title: "Follow up with Emily on budget discrepancy",
    status: "open",
    due_at: daysAgo(-2),
    thread_id: "mock_thr_4",
    category: "follow-up",
    created_at: daysAgo(2),
    completed_at: null,
  },
  {
    id: "TASK-1003",
    title: "Prepare talking points for project sync",
    status: "open",
    due_at: null,
    thread_id: "mock_thr_1",
    category: "meeting",
    created_at: daysAgo(3),
    completed_at: null,
  },
  {
    id: "TASK-1004",
    title: "Review Alice feedback attachment",
    status: "completed",
    due_at: null,
    thread_id: "mock_thr_2",
    category: "review",
    created_at: daysAgo(7),
    completed_at: daysAgo(5),
  },
];
