"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";

import { api } from "@inboxos/lib/api";
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

  const loadTasks = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.getTasks();
      setTasks(data);
    } catch (loadError) {
      setTasks([]);
      setError((loadError as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

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
      setError((completeError as Error).message);
    } finally {
      setCompletingTaskId(null);
    }
  }

  const openCount = tasks.filter((task) => task.status === "open").length;
  const completeCount = tasks.filter(
    (task) => task.status === "completed",
  ).length;
  const surfaceClassName =
    "rounded-[12px] border border-[var(--line)] bg-white shadow-[var(--shadow)]";

  return (
    <main className="grid h-full min-h-0 gap-4">
      <section
        className={cn(
          surfaceClassName,
          "grid gap-4 p-6 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-start",
        )}
      >
        <div>
          <h1 className="m-0 text-[1.55rem] font-semibold text-[var(--text)]">
            Tasks
          </h1>
          <p className="mt-2 text-[0.92rem] text-[var(--muted)]">
            Task workflow with filters, pagination, and completion actions.
          </p>
        </div>
        <div className="grid gap-3 sm:grid-cols-3">
          {[
            { label: "Open", value: openCount },
            { label: "Completed", value: completeCount },
            { label: "Total", value: tasks.length },
          ].map((item) => (
            <div
              key={item.label}
              className="min-w-[120px] rounded-[14px] border border-[var(--line)] bg-[#fafafa] px-4 py-3"
            >
              <strong className="block text-[1.15rem] text-[var(--text)]">
                {item.value}
              </strong>
              <span className="mt-1 block text-[0.78rem] uppercase tracking-[0.08em] text-[var(--muted)]">
                {item.label}
              </span>
            </div>
          ))}
        </div>
      </section>

      <section className={cn(surfaceClassName, "grid gap-4 p-6")}>
        <div>
          <h2 className="m-0 text-[1.05rem] font-semibold text-[var(--text)]">
            Create Task
          </h2>
          <p className="mt-1 text-[0.86rem] text-[var(--muted)]">
            Add a task manually when it does not come from a mail thread.
          </p>
        </div>
        <form
          className="grid gap-3 md:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)_180px_auto]"
          onSubmit={createTask}
        >
          <Input
            value={newTitle}
            onChange={(event) => setNewTitle(event.target.value)}
            placeholder="Task title"
            aria-label="Task title"
          />
          <Input
            value={newCategory}
            onChange={(event) => setNewCategory(event.target.value)}
            placeholder="Category (optional)"
            aria-label="Task category"
          />
          <Input
            type="date"
            value={newDueAt}
            onChange={(event) => setNewDueAt(event.target.value)}
            aria-label="Due date"
          />
          <Button type="submit" disabled={submitting}>
            {submitting ? "Creating..." : "Create"}
          </Button>
        </form>
      </section>

      <section className={cn(surfaceClassName, "grid min-h-0 gap-4 p-6")}>
        <div className="grid gap-3 md:grid-cols-[minmax(0,1.4fr)_220px_220px]">
          <Input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Filter tasks..."
            aria-label="Filter tasks"
          />

          <select
            className="h-10 rounded-md border border-[var(--line)] bg-white px-3 text-sm text-[var(--text)] outline-none"
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
            className="h-10 rounded-md border border-[var(--line)] bg-white px-3 text-sm text-[var(--text)] outline-none"
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
        </div>

        {error ? (
          <p className="m-0 rounded-[12px] border border-[#fecdd3] bg-[#fff1f2] px-4 py-3 text-[0.83rem] text-[#be123c]">
            {error}
          </p>
        ) : null}
        {message ? (
          <p className="m-0 rounded-[12px] border border-[#bbf7d0] bg-[#ecfdf3] px-4 py-3 text-[0.83rem] text-[#166534]">
            {message}
          </p>
        ) : null}
        {loading ? (
          <p className="m-0 text-[0.86rem] text-[var(--muted)]">
            Loading tasks...
          </p>
        ) : null}

        {!loading ? (
          <div className="min-h-0 overflow-auto rounded-[14px] border border-[var(--line)]">
            <table className="w-full min-w-[760px] border-collapse text-left text-[0.86rem]">
              <thead className="bg-[#fafafa] text-[0.73rem] uppercase tracking-[0.08em] text-[var(--muted)]">
                <tr>
                  <th className="px-4 py-3 font-medium">ID</th>
                  <th className="px-4 py-3 font-medium">Title</th>
                  <th className="px-4 py-3 font-medium">Status</th>
                  <th className="px-4 py-3 font-medium">Priority</th>
                  <th className="px-4 py-3 font-medium">Category</th>
                  <th className="px-4 py-3 font-medium">Due</th>
                  <th className="px-4 py-3 font-medium">Actions</th>
                </tr>
              </thead>
              <tbody>
                {pagedTasks.length === 0 ? (
                  <tr>
                    <td
                      colSpan={7}
                      className="px-4 py-10 text-center text-[0.88rem] text-[var(--muted)]"
                    >
                      No tasks in this view.
                    </td>
                  </tr>
                ) : (
                  pagedTasks.map((task) => {
                    const priority = derivePriority(task);
                    return (
                      <tr
                        key={task.id}
                        className="border-t border-[var(--line)] align-middle"
                      >
                        <td className="px-4 py-3 font-mono text-[0.75rem] text-[var(--muted)]">
                          {task.id}
                        </td>
                        <td className="px-4 py-3 font-medium text-[var(--text)]">
                          {task.title}
                        </td>
                        <td className="px-4 py-3">
                          <span
                            className={cn(
                              "inline-flex rounded-full px-2.5 py-1 text-[0.73rem] font-medium capitalize",
                              task.status === "open"
                                ? "bg-[#eff6ff] text-[#1d4ed8]"
                                : "bg-[#ecfdf3] text-[#166534]",
                            )}
                          >
                            {task.status}
                          </span>
                        </td>
                        <td className="px-4 py-3">
                          <span
                            className={cn(
                              "inline-flex rounded-full px-2.5 py-1 text-[0.73rem] font-medium capitalize",
                              priority === "high"
                                ? "bg-[#fff1f2] text-[#be123c]"
                                : priority === "medium"
                                  ? "bg-[#fef3c7] text-[#b45309]"
                                  : "bg-[#f4f4f5] text-[#52525b]",
                            )}
                          >
                            {priority}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-[var(--text)]">
                          {task.category ?? "general"}
                        </td>
                        <td className="px-4 py-3 text-[var(--text)]">
                          {formatDate(task.due_at)}
                        </td>
                        <td className="px-4 py-3">
                          {task.status === "open" ? (
                            <Button
                              variant="outline"
                              onClick={() => completeTask(task.id)}
                              disabled={completingTaskId === task.id}
                            >
                              {completingTaskId === task.id
                                ? "Completing..."
                                : "Complete"}
                            </Button>
                          ) : (
                            <span className="text-[0.82rem] text-[var(--muted)]">
                              Completed
                            </span>
                          )}
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        ) : null}

        <div className="flex flex-col justify-between gap-3 text-[0.84rem] text-[var(--muted)] sm:flex-row sm:items-center">
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
    </main>
  );
}
