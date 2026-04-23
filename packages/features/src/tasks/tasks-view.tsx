"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertCircle,
  CalendarClock,
  CheckCircle2,
  Plus,
  Search,
  Sparkles,
} from "lucide-react";

import { ApiError, api } from "@inboxos/lib/api";
import { formatDate } from "@inboxos/lib/format";
import { TaskItem } from "@inboxos/types";
import { Button } from "@inboxos/ui/button";
import { Input } from "@inboxos/ui/input";
import { cn } from "@inboxos/ui/utils";

type StatusFilter = "all" | "open" | "completed";

const PAGE_SIZE = 8;

function derivePriority(task: TaskItem): "high" | "medium" | "low" {
  if (task.category === "deadline") {
    return "high";
  }

  if (!task.due_at) {
    return "low";
  }

  const dueDate = new Date(task.due_at);
  if (Number.isNaN(dueDate.getTime())) {
    return "medium";
  }

  const daysUntilDue = (dueDate.getTime() - Date.now()) / (1000 * 60 * 60 * 24);
  if (daysUntilDue <= 2) {
    return "high";
  }
  if (daysUntilDue <= 7) {
    return "medium";
  }
  return "low";
}

export function TasksView() {
  const [tasks, setTasks] = useState<TaskItem[]>([]);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [categoryFilter, setCategoryFilter] = useState<string>("all");
  const [pageIndex, setPageIndex] = useState(0);
  const [newTitle, setNewTitle] = useState("");
  const [newCategory, setNewCategory] = useState("");
  const [newDueAt, setNewDueAt] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [completingTaskId, setCompletingTaskId] = useState<string | null>(null);

  const handleAuthError = useCallback((error: unknown): boolean => {
    if (error instanceof ApiError && error.status === 401) {
      window.location.href = "/auth";
      return true;
    }
    return false;
  }, []);

  const loadTasks = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.getTasks();
      setTasks(data);
    } catch (loadError) {
      if (handleAuthError(loadError)) {
        return;
      }
      setTasks([]);
      setError((loadError as Error).message);
    } finally {
      setLoading(false);
    }
  }, [handleAuthError]);

  useEffect(() => {
    void loadTasks();
  }, [loadTasks]);

  const categories = useMemo(() => {
    const values = new Set<string>();
    for (const task of tasks) {
      if (task.category) {
        values.add(task.category);
      }
    }
    return ["all", ...Array.from(values).sort((a, b) => a.localeCompare(b))];
  }, [tasks]);

  const filteredTasks = useMemo(() => {
    const query = search.trim().toLowerCase();

    const next = tasks
      .filter((task) => {
        if (statusFilter !== "all" && task.status !== statusFilter) {
          return false;
        }
        if (
          categoryFilter !== "all" &&
          (task.category ?? "general") !== categoryFilter
        ) {
          return false;
        }
        if (!query) {
          return true;
        }

        const haystack = [
          task.id,
          task.title,
          task.category ?? "",
          task.thread_id ?? "",
        ]
          .join(" ")
          .toLowerCase();
        return haystack.includes(query);
      })
      .sort((a, b) => {
        if (a.status !== b.status) {
          return a.status === "open" ? -1 : 1;
        }
        return (
          new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
        );
      });

    return next;
  }, [categoryFilter, search, statusFilter, tasks]);

  const totalPages = Math.max(1, Math.ceil(filteredTasks.length / PAGE_SIZE));
  const pagedTasks = filteredTasks.slice(
    pageIndex * PAGE_SIZE,
    pageIndex * PAGE_SIZE + PAGE_SIZE,
  );

  useEffect(() => {
    setPageIndex(0);
  }, [search, statusFilter, categoryFilter]);

  useEffect(() => {
    if (pageIndex > totalPages - 1) {
      setPageIndex(Math.max(0, totalPages - 1));
    }
  }, [pageIndex, totalPages]);

  const summary = useMemo(() => {
    const openTasks = tasks.filter((task) => task.status === "open");
    const completedTasks = tasks.length - openTasks.length;
    const urgentTasks = openTasks.filter(
      (task) => derivePriority(task) === "high",
    ).length;

    return {
      total: tasks.length,
      open: openTasks.length,
      completed: completedTasks,
      urgent: urgentTasks,
    };
  }, [tasks]);

  async function createTask(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!newTitle.trim()) {
      setError("Task title is required.");
      return;
    }

    setSubmitting(true);
    setMessage(null);
    setError(null);
    try {
      await api.createTask({
        title: newTitle.trim(),
        category: newCategory.trim() || null,
        due_at: newDueAt ? new Date(newDueAt).toISOString() : null,
        thread_id: null,
      });
      await loadTasks();
      setNewTitle("");
      setNewCategory("");
      setNewDueAt("");
      setMessage("Task created.");
    } catch (createError) {
      if (handleAuthError(createError)) {
        return;
      }
      setError((createError as Error).message);
    } finally {
      setSubmitting(false);
    }
  }

  async function completeTask(taskId: string) {
    setCompletingTaskId(taskId);
    setMessage(null);
    setError(null);
    try {
      await api.completeTask(taskId);
      await loadTasks();
      setMessage("Task marked complete.");
    } catch (completeError) {
      if (handleAuthError(completeError)) {
        return;
      }
      setError((completeError as Error).message);
    } finally {
      setCompletingTaskId(null);
    }
  }

  return (
    <main className="grid h-full min-h-0 gap-5 overflow-hidden rounded-[28px] border border-[color:var(--line)] bg-[rgba(255,255,255,0.72)] p-4 shadow-[var(--shadow-soft)] backdrop-blur-xl md:grid-cols-[minmax(0,1.5fr)_360px] md:p-5">
      <section className="grid min-h-0 grid-rows-[auto_auto_minmax(0,1fr)_auto] gap-4">
        <header className="rounded-[24px] border border-white/75 bg-[linear-gradient(135deg,rgba(255,255,255,0.9),rgba(240,246,255,0.88)_52%,rgba(226,237,255,0.94))] p-5 shadow-[0_24px_56px_rgba(15,23,42,0.12)]">
          <div className="flex flex-col gap-5">
            <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
              <div>
                <span className="inline-flex rounded-full border border-white/80 bg-white/70 px-3 py-1 text-[0.7rem] font-semibold uppercase tracking-[0.16em] text-[color:var(--accent-strong)]">
                  Task cockpit
                </span>
                <h1 className="mt-3 text-[2rem] font-semibold tracking-[-0.06em] text-[var(--text)]">
                  Work that actually moves.
                </h1>
                <p className="mt-2 max-w-[34rem] text-[0.95rem] leading-7 text-[color:var(--text-muted)]">
                  Capture follow-ups quickly, filter the noise, and keep urgent
                  work visible without turning the page into a spreadsheet.
                </p>
              </div>
              <div className="inline-flex items-center gap-2 rounded-full border border-white/80 bg-white/75 px-4 py-2 text-[0.82rem] font-medium text-[color:var(--text-muted)] shadow-[0_12px_24px_rgba(15,23,42,0.06)]">
                <Sparkles size={15} className="text-[color:var(--accent)]" />
                {summary.open} open across {categories.length - 1} categories
              </div>
            </div>
            <div className="grid gap-3 md:grid-cols-3">
              {[
                {
                  label: "Open",
                  value: summary.open,
                  icon: AlertCircle,
                  tone: "text-[#b45309] bg-[#fff7ed] border-[#fed7aa]",
                },
                {
                  label: "Urgent",
                  value: summary.urgent,
                  icon: CalendarClock,
                  tone: "text-[#be123c] bg-[#fff1f2] border-[#fecdd3]",
                },
                {
                  label: "Completed",
                  value: summary.completed,
                  icon: CheckCircle2,
                  tone: "text-[#166534] bg-[#ecfdf3] border-[#bbf7d0]",
                },
              ].map((item) => (
                <article
                  key={item.label}
                  className="rounded-[20px] border border-white/75 bg-white/72 p-4 shadow-[0_16px_34px_rgba(15,23,42,0.08)]"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="m-0 text-[0.76rem] font-semibold uppercase tracking-[0.14em] text-[color:var(--text-subtle)]">
                        {item.label}
                      </p>
                      <p className="mt-3 text-[2rem] font-semibold tracking-[-0.06em] text-[var(--text)]">
                        {item.value}
                      </p>
                    </div>
                    <span
                      className={cn(
                        "inline-flex h-11 w-11 items-center justify-center rounded-[14px] border",
                        item.tone,
                      )}
                    >
                      <item.icon size={18} />
                    </span>
                  </div>
                </article>
              ))}
            </div>
          </div>
        </header>

        <section className="grid gap-3 rounded-[22px] border border-[color:var(--line)] bg-[rgba(255,255,255,0.8)] p-4 shadow-[0_16px_34px_rgba(15,23,42,0.08)] md:grid-cols-[minmax(0,1.3fr)_200px_200px]">
          <label className="relative block">
            <Search
              size={16}
              className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-[color:var(--text-subtle)]"
            />
            <Input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search titles, categories, or thread IDs"
              aria-label="Filter tasks"
              className="pl-11"
            />
          </label>

          <select
            className="h-11 rounded-[14px] border border-[color:var(--line)] bg-[color:var(--surface-1)] px-4 text-[0.9rem] text-[color:var(--text)] outline-none transition-[border-color,box-shadow,background-color] duration-150 ease-[var(--ease-out)] focus:border-[color:var(--line-emphasis)] focus:bg-white focus:shadow-[0_0_0_4px_rgba(37,99,235,0.12)]"
            value={statusFilter}
            onChange={(event) =>
              setStatusFilter(event.target.value as StatusFilter)
            }
            aria-label="Filter by status"
          >
            <option value="all">All status</option>
            <option value="open">Open</option>
            <option value="completed">Completed</option>
          </select>

          <select
            className="h-11 rounded-[14px] border border-[color:var(--line)] bg-[color:var(--surface-1)] px-4 text-[0.9rem] text-[color:var(--text)] outline-none transition-[border-color,box-shadow,background-color] duration-150 ease-[var(--ease-out)] focus:border-[color:var(--line-emphasis)] focus:bg-white focus:shadow-[0_0_0_4px_rgba(37,99,235,0.12)]"
            value={categoryFilter}
            onChange={(event) => setCategoryFilter(event.target.value)}
            aria-label="Filter by category"
          >
            {categories.map((category) => (
              <option key={category} value={category}>
                {category === "all" ? "All categories" : category}
              </option>
            ))}
          </select>
        </section>

        {error ? (
          <p className="m-0 rounded-[16px] border border-[#fecdd3] bg-[#fff1f2] px-4 py-3 text-[0.83rem] text-[#be123c]">
            {error}
          </p>
        ) : null}
        {message ? (
          <p className="m-0 rounded-[16px] border border-[#bbf7d0] bg-[#ecfdf3] px-4 py-3 text-[0.83rem] text-[#166534]">
            {message}
          </p>
        ) : null}
        {loading ? (
          <p className="m-0 text-[0.86rem] text-[var(--muted)]">
            Loading tasks...
          </p>
        ) : null}

        {!loading ? (
          <div className="min-h-0 overflow-auto rounded-[24px] border border-[color:var(--line)] bg-[rgba(255,255,255,0.82)] p-4 shadow-[0_18px_40px_rgba(15,23,42,0.08)]">
            {pagedTasks.length === 0 ? (
              <div className="grid min-h-[320px] place-items-center rounded-[20px] border border-dashed border-[color:var(--line-strong)] bg-[color:var(--surface-1)] px-6 text-center">
                <div>
                  <p className="m-0 text-[1rem] font-semibold tracking-[-0.03em] text-[var(--text)]">
                    No tasks in this view
                  </p>
                  <p className="mt-2 text-[0.9rem] leading-6 text-[color:var(--text-muted)]">
                    Try another filter or create a fresh task from the composer.
                  </p>
                </div>
              </div>
            ) : (
              <div className="grid gap-3">
                {pagedTasks.map((task) => {
                  const priority = derivePriority(task);
                  return (
                    <article
                      key={task.id}
                      className="grid gap-4 rounded-[22px] border border-[color:var(--line)] bg-[linear-gradient(180deg,rgba(255,255,255,0.96),rgba(247,250,255,0.94))] p-4 shadow-[0_14px_28px_rgba(15,23,42,0.07)] transition-[transform,border-color,box-shadow] duration-150 ease-[var(--ease-out)] hover:-translate-y-[1px] hover:border-[color:var(--line-emphasis)] hover:shadow-[0_18px_36px_rgba(15,23,42,0.1)]"
                    >
                      <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                        <div className="min-w-0">
                          <div className="mb-2 flex flex-wrap items-center gap-2">
                            <span
                              className={cn(
                                "inline-flex rounded-full border px-2.5 py-1 text-[0.72rem] font-semibold capitalize",
                                task.status === "open"
                                  ? "border-[#bfdbfe] bg-[#eff6ff] text-[#1d4ed8]"
                                  : "border-[#bbf7d0] bg-[#ecfdf3] text-[#166534]",
                              )}
                            >
                              {task.status}
                            </span>
                            <span
                              className={cn(
                                "inline-flex rounded-full border px-2.5 py-1 text-[0.72rem] font-semibold capitalize",
                                priority === "high"
                                  ? "border-[#fecdd3] bg-[#fff1f2] text-[#be123c]"
                                  : priority === "medium"
                                    ? "border-[#fde68a] bg-[#fffbeb] text-[#b45309]"
                                    : "border-[#e4e4e7] bg-[#fafafa] text-[#52525b]",
                              )}
                            >
                              {priority} priority
                            </span>
                          </div>
                          <h2 className="m-0 text-[1.02rem] font-semibold tracking-[-0.03em] text-[var(--text)]">
                            {task.title}
                          </h2>
                          <div className="mt-3 flex flex-wrap gap-x-5 gap-y-2 text-[0.82rem] text-[color:var(--text-muted)]">
                            <span>Category: {task.category ?? "general"}</span>
                            <span>Due: {formatDate(task.due_at)}</span>
                            <span className="font-mono text-[0.76rem] text-[color:var(--text-subtle)]">
                              {task.id}
                            </span>
                          </div>
                        </div>
                        <div className="flex items-center gap-2">
                          {task.status === "open" ? (
                            <Button
                              variant="outline"
                              onClick={() => completeTask(task.id)}
                              disabled={completingTaskId === task.id}
                            >
                              {completingTaskId === task.id
                                ? "Completing..."
                                : "Mark complete"}
                            </Button>
                          ) : (
                            <span className="rounded-full border border-[#bbf7d0] bg-[#ecfdf3] px-3 py-1.5 text-[0.78rem] font-semibold text-[#166534]">
                              Completed
                            </span>
                          )}
                        </div>
                      </div>
                    </article>
                  );
                })}
              </div>
            )}
          </div>
        ) : null}

        <div className="flex flex-col gap-3 text-[0.84rem] text-[var(--muted)] sm:flex-row sm:items-center sm:justify-between">
          <p className="m-0">
            Page {Math.min(pageIndex + 1, totalPages)} of {totalPages}
          </p>
          <div className="flex flex-wrap gap-2">
            <Button
              variant="outline"
              onClick={() => setPageIndex(0)}
              disabled={pageIndex === 0}
            >
              First
            </Button>
            <Button
              variant="outline"
              onClick={() => setPageIndex((value) => Math.max(0, value - 1))}
              disabled={pageIndex === 0}
            >
              Previous
            </Button>
            <Button
              variant="outline"
              onClick={() =>
                setPageIndex((value) => Math.min(totalPages - 1, value + 1))
              }
              disabled={pageIndex >= totalPages - 1}
            >
              Next
            </Button>
            <Button
              variant="outline"
              onClick={() => setPageIndex(totalPages - 1)}
              disabled={pageIndex >= totalPages - 1}
            >
              Last
            </Button>
          </div>
        </div>
      </section>

      <aside className="grid min-h-0 grid-rows-[auto_auto] gap-4">
        <section className="rounded-[24px] border border-[color:var(--line)] bg-[linear-gradient(180deg,rgba(255,255,255,0.94),rgba(243,247,255,0.9))] p-5 shadow-[0_24px_48px_rgba(15,23,42,0.1)]">
          <div className="mb-4">
            <span className="inline-flex rounded-full border border-white/80 bg-white/70 px-3 py-1 text-[0.7rem] font-semibold uppercase tracking-[0.16em] text-[color:var(--accent-strong)]">
              Quick capture
            </span>
            <h2 className="mt-3 text-[1.2rem] font-semibold tracking-[-0.04em] text-[var(--text)]">
              Add a task without breaking flow
            </h2>
            <p className="mt-2 text-[0.88rem] leading-6 text-[color:var(--text-muted)]">
              Keep the title crisp, use a category only when it helps grouping,
              and attach a due date when it changes urgency.
            </p>
          </div>
          <form className="grid gap-3" onSubmit={createTask}>
            <Input
              value={newTitle}
              onChange={(event) => setNewTitle(event.target.value)}
              placeholder="Task title"
              aria-label="Task title"
            />
            <Input
              value={newCategory}
              onChange={(event) => setNewCategory(event.target.value)}
              placeholder="Category"
              aria-label="Task category"
            />
            <Input
              type="date"
              value={newDueAt}
              onChange={(event) => setNewDueAt(event.target.value)}
              aria-label="Due date"
            />
            <Button
              type="submit"
              disabled={submitting}
              className="mt-1 h-11 justify-center rounded-[16px]"
            >
              <Plus size={16} />
              {submitting ? "Creating..." : "Create task"}
            </Button>
          </form>
        </section>

        <section className="rounded-[24px] border border-[color:var(--line)] bg-[rgba(255,255,255,0.82)] p-5 shadow-[0_18px_40px_rgba(15,23,42,0.08)]">
          <h2 className="m-0 text-[1rem] font-semibold tracking-[-0.03em] text-[var(--text)]">
            View summary
          </h2>
          <div className="mt-4 grid gap-3 text-[0.86rem] text-[color:var(--text-muted)]">
            <div className="rounded-[18px] border border-[color:var(--line)] bg-[color:var(--surface-1)] p-4">
              <p className="m-0 text-[0.76rem] font-semibold uppercase tracking-[0.14em] text-[color:var(--text-subtle)]">
                Total tasks
              </p>
              <p className="mt-2 text-[1.8rem] font-semibold tracking-[-0.05em] text-[var(--text)]">
                {summary.total}
              </p>
            </div>
            <div className="rounded-[18px] border border-[color:var(--line)] bg-[color:var(--surface-1)] p-4">
              <p className="m-0 text-[0.76rem] font-semibold uppercase tracking-[0.14em] text-[color:var(--text-subtle)]">
                Current view
              </p>
              <p className="mt-2 text-[0.95rem] font-semibold text-[var(--text)]">
                {filteredTasks.length} matching tasks
              </p>
              <p className="mt-1 text-[0.82rem] leading-6 text-[color:var(--text-muted)]">
                Page {Math.min(pageIndex + 1, totalPages)} of {totalPages}
              </p>
            </div>
          </div>
        </section>
      </aside>
    </main>
  );
}
