"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";

import { api } from "@inboxos/lib/api";
import { formatDate } from "@inboxos/lib/format";
import { AuthSessionResponse, TaskItem } from "@inboxos/types";

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
  const [session, setSession] = useState<AuthSessionResponse | null>(null);
  const [tasks, setTasks] = useState<TaskItem[]>([]);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [categoryFilter, setCategoryFilter] = useState<string>("all");
  const [accountFilter, setAccountFilter] = useState<string>("all");
  const [pageIndex, setPageIndex] = useState(0);
  const [newTitle, setNewTitle] = useState("");
  const [newCategory, setNewCategory] = useState("");
  const [newDueAt, setNewDueAt] = useState("");
  const [newLinkedAccountId, setNewLinkedAccountId] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [completingTaskId, setCompletingTaskId] = useState<string | null>(null);
  const linkedAccounts = useMemo(
    () =>
      (session?.linked_accounts ?? []).filter(
        (account) => account.status === "active",
      ),
    [session?.linked_accounts],
  );

  const loadTasks = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [nextSession, data] = await Promise.all([
        api.getSession(),
        api.getTasks(),
      ]);
      if (!nextSession.authenticated) {
        window.location.href = "/auth";
        return;
      }
      setSession(nextSession);
      setNewLinkedAccountId(
        (current) => current || nextSession.active_account_id || "",
      );
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
        if (
          accountFilter !== "all" &&
          (task.linked_account_id ?? "__none__") !== accountFilter
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
          task.account_email ?? "",
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
  }, [accountFilter, categoryFilter, search, statusFilter, tasks]);

  const totalPages = Math.max(1, Math.ceil(filteredTasks.length / PAGE_SIZE));
  const pagedTasks = filteredTasks.slice(
    pageIndex * PAGE_SIZE,
    pageIndex * PAGE_SIZE + PAGE_SIZE,
  );

  useEffect(() => {
    setPageIndex(0);
  }, [accountFilter, categoryFilter, search, statusFilter]);

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
        linked_account_id:
          newLinkedAccountId || session?.active_account_id || null,
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

  return (
    <main className="tasks-layout">
      <section className="panel-surface tasks-hero">
        <div>
          <h1>Tasks</h1>
          <p>
            Task workflow across all linked accounts, with account-aware
            filtering and creation.
          </p>
        </div>
        <div className="task-kpis">
          <div>
            <strong>{openCount}</strong>
            <span>Open</span>
          </div>
          <div>
            <strong>{completeCount}</strong>
            <span>Completed</span>
          </div>
          <div>
            <strong>{tasks.length}</strong>
            <span>Total</span>
          </div>
        </div>
      </section>

      <section className="panel-surface task-create">
        <h2>Create Task</h2>
        <form className="task-create-form" onSubmit={createTask}>
          <select
            value={newLinkedAccountId}
            onChange={(event) => setNewLinkedAccountId(event.target.value)}
            aria-label="Task account"
          >
            {linkedAccounts.map((account) => (
              <option key={account.id} value={account.id}>
                {account.provider_account_ref ?? account.display_name}
              </option>
            ))}
          </select>
          <input
            value={newTitle}
            onChange={(event) => setNewTitle(event.target.value)}
            placeholder="Task title"
            aria-label="Task title"
          />
          <input
            value={newCategory}
            onChange={(event) => setNewCategory(event.target.value)}
            placeholder="Category (optional)"
            aria-label="Task category"
          />
          <input
            type="date"
            value={newDueAt}
            onChange={(event) => setNewDueAt(event.target.value)}
            aria-label="Due date"
          />
          <button
            className="btn btn-primary"
            type="submit"
            disabled={submitting}
          >
            {submitting ? "Creating..." : "Create"}
          </button>
        </form>
      </section>

      <section className="panel-surface tasks-table-wrap">
        <div className="tasks-toolbar">
          <input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Filter tasks..."
            aria-label="Filter tasks"
          />

          <select
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

          <select
            value={accountFilter}
            onChange={(event) => setAccountFilter(event.target.value)}
            aria-label="Filter by account"
          >
            <option value="all">All accounts</option>
            {linkedAccounts.map((account) => (
              <option key={account.id} value={account.id}>
                {account.provider_account_ref ?? account.display_name}
              </option>
            ))}
          </select>
        </div>

        {error ? <p className="status error">{error}</p> : null}
        {message ? <p className="status">{message}</p> : null}
        {loading ? <p className="muted">Loading tasks...</p> : null}

        {!loading ? (
          <div className="table-shell">
            <table className="tasks-table">
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Title</th>
                  <th>Account</th>
                  <th>Status</th>
                  <th>Priority</th>
                  <th>Category</th>
                  <th>Due</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {pagedTasks.length === 0 ? (
                  <tr>
                    <td colSpan={8} className="empty-cell">
                      No tasks in this view.
                    </td>
                  </tr>
                ) : (
                  pagedTasks.map((task) => {
                    const priority = derivePriority(task);
                    return (
                      <tr key={task.id}>
                        <td>{task.id}</td>
                        <td className="task-title-cell">{task.title}</td>
                        <td>{task.account_email ?? "Unassigned"}</td>
                        <td>
                          <span className={`pill status-${task.status}`}>
                            {task.status}
                          </span>
                        </td>
                        <td>
                          <span className={`pill priority-${priority}`}>
                            {priority}
                          </span>
                        </td>
                        <td>{task.category ?? "general"}</td>
                        <td>{formatDate(task.due_at)}</td>
                        <td>
                          {task.status === "open" ? (
                            <button
                              className="btn"
                              onClick={() => completeTask(task.id)}
                              disabled={completingTaskId === task.id}
                            >
                              {completingTaskId === task.id
                                ? "Completing..."
                                : "Complete"}
                            </button>
                          ) : (
                            <span className="muted">Completed</span>
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

        <div className="tasks-pagination">
          <p>
            Page {Math.min(pageIndex + 1, totalPages)} of {totalPages}
          </p>
          <div>
            <button
              className="btn"
              onClick={() => setPageIndex(0)}
              disabled={pageIndex === 0}
            >
              First
            </button>
            <button
              className="btn"
              onClick={() => setPageIndex((value) => Math.max(0, value - 1))}
              disabled={pageIndex === 0}
            >
              Previous
            </button>
            <button
              className="btn"
              onClick={() =>
                setPageIndex((value) => Math.min(totalPages - 1, value + 1))
              }
              disabled={pageIndex >= totalPages - 1}
            >
              Next
            </button>
            <button
              className="btn"
              onClick={() => setPageIndex(totalPages - 1)}
              disabled={pageIndex >= totalPages - 1}
            >
              Last
            </button>
          </div>
        </div>
      </section>
    </main>
  );
}
