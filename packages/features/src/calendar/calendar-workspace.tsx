"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import {
  CalendarPlus,
  ChevronLeft,
  ChevronRight,
  Clock3,
  MapPin,
} from "lucide-react";

import { api } from "@inboxos/lib/api";
import {
  AuthSessionResponse,
  CalendarEvent as ApiCalendarEvent,
} from "@inboxos/types";
import { ConfirmDialog } from "@inboxos/ui/confirm-dialog";

import {
  CalendarCreateEventDialog,
  CalendarEventDetailsDialog,
} from "./calendar-dialogs";

type ViewMode = "day" | "week" | "month";
type EventTone = "blue" | "green" | "amber" | "rose";

type CalendarEvent = {
  id: string;
  title: string;
  startsAt: Date;
  endsAt: Date;
  location: string;
  description: string;
  isAllDay: boolean;
  htmlLink: string | null;
  canDelete: boolean;
  tone: EventTone;
};

type EventFormState = {
  title: string;
  startsAt: string;
  endsAt: string;
  location: string;
  description: string;
  isAllDay: boolean;
};

const calendarViews: ViewMode[] = ["day", "week", "month"];
const weekdayLabels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const scheduleStartHour = 0;
const scheduleEndHour = 24;
const slotsPerHour = 2;
const scheduleSlotMinutes = 60 / slotsPerHour;
const scheduleRowHeight = 34;
const totalScheduleSlots = (scheduleEndHour - scheduleStartHour) * slotsPerHour;
const toneScale: EventTone[] = ["blue", "green", "amber", "rose"];

function dateKey(value: Date): string {
  const y = value.getFullYear();
  const m = String(value.getMonth() + 1).padStart(2, "0");
  const d = String(value.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

function startOfDay(value: Date): Date {
  return new Date(value.getFullYear(), value.getMonth(), value.getDate());
}

function startOfMonth(value: Date): Date {
  return new Date(value.getFullYear(), value.getMonth(), 1);
}

function startOfWeek(value: Date): Date {
  const dayIndex = (value.getDay() + 6) % 7;
  return addDays(value, -dayIndex);
}

function addDays(value: Date, days: number): Date {
  const next = new Date(value);
  next.setDate(next.getDate() + days);
  return next;
}

function addHours(value: Date, hours: number): Date {
  const next = new Date(value);
  next.setHours(next.getHours() + hours);
  return next;
}

function addMonths(value: Date, months: number): Date {
  return new Date(value.getFullYear(), value.getMonth() + months, 1);
}

function sameDay(left: Date, right: Date): boolean {
  return dateKey(left) === dateKey(right);
}

function sameMonth(left: Date, right: Date): boolean {
  return (
    left.getFullYear() === right.getFullYear() &&
    left.getMonth() === right.getMonth()
  );
}

function formatMonthLabel(value: Date): string {
  return value.toLocaleDateString(undefined, {
    month: "long",
    year: "numeric",
  });
}

function formatSelectedLabel(value: Date): string {
  return value.toLocaleDateString(undefined, {
    weekday: "long",
    month: "long",
    day: "numeric",
    year: "numeric",
  });
}

function formatTimeRange(start: Date, end: Date, isAllDay = false): string {
  if (isAllDay) {
    return "All day";
  }
  return `${start.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })} - ${end.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}`;
}

function formatTimeLabel(hour: number): string {
  return new Date(2026, 0, 1, hour).toLocaleTimeString([], {
    hour: "numeric",
  });
}

function formatViewTitle(
  viewMode: ViewMode,
  selectedDate: Date,
  visibleMonth: Date,
): string {
  if (viewMode === "day") {
    return selectedDate.toLocaleDateString(undefined, {
      weekday: "long",
      month: "long",
      day: "numeric",
    });
  }

  if (viewMode === "week") {
    return selectedDate.toLocaleDateString(undefined, {
      month: "long",
      year: "numeric",
    });
  }

  return formatMonthLabel(visibleMonth);
}

function toneForEvent(id: string): EventTone {
  const total = id.split("").reduce((sum, char) => sum + char.charCodeAt(0), 0);
  return toneScale[total % toneScale.length];
}

function normalizeEvent(event: ApiCalendarEvent): CalendarEvent {
  return {
    id: event.id,
    title: event.title,
    startsAt: new Date(event.starts_at),
    endsAt: new Date(event.ends_at),
    location: event.location ?? "Google Calendar",
    description: event.description ?? "",
    isAllDay: event.is_all_day,
    htmlLink: event.html_link,
    canDelete: event.can_delete,
    tone: toneForEvent(event.id),
  };
}

function eventDays(event: CalendarEvent): Date[] {
  const days: Date[] = [];
  const start = startOfDay(event.startsAt);
  const end = event.isAllDay
    ? addDays(startOfDay(event.endsAt), -1)
    : startOfDay(new Date(event.endsAt.getTime() - 1));

  for (
    let cursor = start;
    cursor.getTime() <= Math.max(start.getTime(), end.getTime());
    cursor = addDays(cursor, 1)
  ) {
    days.push(new Date(cursor));
  }

  return days;
}

function toDateTimeInputValue(value: Date): string {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  const hour = String(value.getHours()).padStart(2, "0");
  const minute = String(value.getMinutes()).padStart(2, "0");
  return `${year}-${month}-${day}T${hour}:${minute}`;
}

function buildDefaultEventForm(selectedDate: Date): EventFormState {
  const start = new Date(selectedDate);
  start.setHours(9, 0, 0, 0);
  const end = addHours(start, 1);
  return {
    title: "",
    startsAt: toDateTimeInputValue(start),
    endsAt: toDateTimeInputValue(end),
    location: "",
    description: "",
    isAllDay: false,
  };
}

export function CalendarWorkspace() {
  const today = useMemo(() => new Date(), []);
  const [session, setSession] = useState<AuthSessionResponse | null>(null);
  const [viewMode, setViewMode] = useState<ViewMode>("week");
  const [visibleMonth, setVisibleMonth] = useState<Date>(startOfMonth(today));
  const [selectedDate, setSelectedDate] = useState<Date>(new Date(today));
  const [events, setEvents] = useState<CalendarEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [showEventForm, setShowEventForm] = useState(false);
  const [eventForm, setEventForm] = useState<EventFormState>(
    buildDefaultEventForm(today),
  );
  const [submittingEvent, setSubmittingEvent] = useState(false);
  const [selectedEventId, setSelectedEventId] = useState<string | null>(null);
  const [deletingEvent, setDeletingEvent] = useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);

  const fetchRange = useMemo(() => {
    const monthStart = startOfMonth(visibleMonth);
    return {
      start: addDays(startOfWeek(monthStart), -7),
      end: addDays(startOfWeek(addMonths(monthStart, 2)), 14),
    };
  }, [visibleMonth]);

  const loadEvents = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      const [nextSession, nextEvents] = await Promise.all([
        api.getSession(),
        api.getCalendarEvents(
          fetchRange.start.toISOString(),
          fetchRange.end.toISOString(),
        ),
      ]);
      if (!nextSession.authenticated) {
        window.location.href = "/auth";
        return;
      }

      setSession(nextSession);
      setEvents(nextEvents.map(normalizeEvent));
    } catch (loadError) {
      setError((loadError as Error).message);
      setEvents([]);
    } finally {
      setLoading(false);
    }
  }, [fetchRange.end, fetchRange.start]);

  useEffect(() => {
    void loadEvents();
  }, [loadEvents]);

  const eventsByDay = useMemo(() => {
    const map = new Map<string, CalendarEvent[]>();

    for (const event of events) {
      for (const day of eventDays(event)) {
        const key = dateKey(day);
        const current = map.get(key) ?? [];
        current.push(event);
        current.sort((a, b) => a.startsAt.getTime() - b.startsAt.getTime());
        map.set(key, current);
      }
    }

    return map;
  }, [events]);

  const monthDays = useMemo(() => {
    const first = startOfMonth(visibleMonth);
    const mondayOffset = (first.getDay() + 6) % 7;
    const gridStart = addDays(first, -mondayOffset);

    return Array.from({ length: 42 }, (_, index) => {
      const date = addDays(gridStart, index);
      return {
        date,
        inMonth: date.getMonth() === visibleMonth.getMonth(),
        isToday: sameDay(date, today),
        isSelected: sameDay(date, selectedDate),
        eventCount: (eventsByDay.get(dateKey(date)) ?? []).length,
      };
    });
  }, [eventsByDay, selectedDate, today, visibleMonth]);

  const selectedDayEvents = useMemo(() => {
    return eventsByDay.get(dateKey(selectedDate)) ?? [];
  }, [eventsByDay, selectedDate]);

  const visibleWeekDays = useMemo(() => {
    const weekStart = startOfWeek(selectedDate);
    return Array.from({ length: 7 }, (_, index) => addDays(weekStart, index));
  }, [selectedDate]);

  const visibleScheduleDays = useMemo(() => {
    return viewMode === "day" ? [selectedDate] : visibleWeekDays;
  }, [selectedDate, viewMode, visibleWeekDays]);

  const scheduleTemplateColumns = `${viewMode === "day" ? 62 : 56}px repeat(${visibleScheduleDays.length}, minmax(${viewMode === "day" ? 180 : 112}px, 1fr))`;

  const scheduleEvents = useMemo(() => {
    return events
      .filter((event) => !event.isAllDay)
      .map((event) => {
        const dayIndex = visibleScheduleDays.findIndex((day) =>
          sameDay(day, event.startsAt),
        );
        const startMinutes =
          (event.startsAt.getHours() - scheduleStartHour) * 60 +
          event.startsAt.getMinutes();
        const durationMinutes = Math.max(
          scheduleSlotMinutes,
          (event.endsAt.getTime() - event.startsAt.getTime()) / 60000,
        );

        if (
          dayIndex === -1 ||
          startMinutes >= (scheduleEndHour - scheduleStartHour) * 60
        ) {
          return null;
        }

        const rowStart = Math.max(
          1,
          Math.floor(startMinutes / scheduleSlotMinutes) + 1,
        );
        const rowSpan = Math.max(
          1,
          Math.ceil(durationMinutes / scheduleSlotMinutes),
        );

        return {
          ...event,
          gridColumn: dayIndex + 2,
          gridRow: `${rowStart} / span ${Math.min(rowSpan, totalScheduleSlots - rowStart + 1)}`,
        };
      })
      .filter(
        (
          event,
        ): event is CalendarEvent & { gridColumn: number; gridRow: string } =>
          event !== null,
      );
  }, [events, visibleScheduleDays]);

  const allDayEventsByVisibleDay = useMemo(() => {
    return visibleScheduleDays.map((day) =>
      (eventsByDay.get(dateKey(day)) ?? []).filter((event) => event.isAllDay),
    );
  }, [eventsByDay, visibleScheduleDays]);

  const upcomingEvents = useMemo(() => {
    return [...events]
      .filter(
        (event) =>
          event.startsAt.getTime() >= startOfDay(selectedDate).getTime(),
      )
      .sort((a, b) => a.startsAt.getTime() - b.startsAt.getTime())
      .slice(0, 6);
  }, [events, selectedDate]);

  const selectedEvent = useMemo(
    () => events.find((event) => event.id === selectedEventId) ?? null,
    [events, selectedEventId],
  );

  function moveView(direction: -1 | 1) {
    if (viewMode === "month") {
      const nextMonth = addMonths(visibleMonth, direction);
      const nextDate = addMonths(selectedDate, direction);
      setVisibleMonth(nextMonth);
      setSelectedDate(nextDate);
      return;
    }

    const nextDate = addDays(
      selectedDate,
      viewMode === "week" ? direction * 7 : direction,
    );
    setSelectedDate(nextDate);
    setVisibleMonth(startOfMonth(nextDate));
  }

  function jumpToToday() {
    const nextToday = new Date();
    setVisibleMonth(startOfMonth(nextToday));
    setSelectedDate(nextToday);
  }

  function changeView(nextView: ViewMode) {
    setViewMode(nextView);
    if (nextView === "month") {
      setVisibleMonth(startOfMonth(selectedDate));
    }
  }

  function openEventForm() {
    setSelectedEventId(null);
    setEventForm(buildDefaultEventForm(selectedDate));
    setShowEventForm(true);
    setError(null);
    setMessage(null);
  }

  function openEventDetails(event: CalendarEvent) {
    setShowEventForm(false);
    setSelectedEventId(event.id);
    setError(null);
    setMessage(null);
  }

  async function submitEvent(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmittingEvent(true);
    setError(null);
    setMessage(null);

    try {
      const startsAt = eventForm.isAllDay
        ? new Date(`${eventForm.startsAt}T00:00:00`)
        : new Date(eventForm.startsAt);
      const endsAt = eventForm.isAllDay
        ? new Date(`${eventForm.endsAt}T00:00:00`)
        : new Date(eventForm.endsAt);

      const created = await api.createCalendarEvent({
        title: eventForm.title.trim(),
        starts_at: startsAt.toISOString(),
        ends_at: endsAt.toISOString(),
        is_all_day: eventForm.isAllDay,
        location: eventForm.location.trim() || null,
        description: eventForm.description.trim() || null,
      });
      const createdDate = new Date(created.starts_at);
      setSelectedDate(createdDate);
      setVisibleMonth(startOfMonth(createdDate));
      setShowEventForm(false);
      setSelectedEventId(created.id);
      setMessage("Calendar event created.");
      await loadEvents();
    } catch (submitError) {
      setError((submitError as Error).message);
    } finally {
      setSubmittingEvent(false);
    }
  }

  async function deleteSelectedEvent() {
    if (!selectedEvent) {
      return;
    }

    setDeletingEvent(true);
    setError(null);
    setMessage(null);

    try {
      await api.deleteCalendarEvent(selectedEvent.id);
      setShowDeleteConfirm(false);
      setSelectedEventId(null);
      setMessage("Calendar event deleted.");
      await loadEvents();
    } catch (deleteError) {
      setError((deleteError as Error).message);
    } finally {
      setDeletingEvent(false);
    }
  }

  return (
    <>
      <main className="calendar-shell panel-surface">
        <section className="calendar-main">
          <div className="calendar-title-row">
            <div className="calendar-title-copy">
              <h1>{formatViewTitle(viewMode, selectedDate, visibleMonth)}</h1>
              <p>
                {(session?.account_email ?? session?.user?.primary_email)
                  ? `Primary Google Calendar for ${session?.account_email ?? session?.user?.primary_email}`
                  : "Primary Google Calendar"}
              </p>
            </div>
            <div
              className="calendar-view-switcher"
              aria-label="Calendar view switcher"
              role="tablist"
            >
              {calendarViews.map((mode) => (
                <button
                  key={mode}
                  type="button"
                  className={viewMode === mode ? "active" : ""}
                  aria-selected={viewMode === mode}
                  role="tab"
                  onClick={() => changeView(mode)}
                >
                  {mode[0].toUpperCase() + mode.slice(1)}
                </button>
              ))}
            </div>
            <div className="calendar-controls">
              <button
                type="button"
                aria-label="Previous period"
                onClick={() => moveView(-1)}
              >
                <ChevronLeft size={14} />
              </button>
              <button type="button" className="today-btn" onClick={jumpToToday}>
                Today
              </button>
              <button
                type="button"
                aria-label="Next period"
                onClick={() => moveView(1)}
              >
                <ChevronRight size={14} />
              </button>
            </div>
          </div>

          {message ? <p className="status inline-status">{message}</p> : null}
          {error ? <p className="status error inline-status">{error}</p> : null}
          {loading ? (
            <p className="list-empty">Loading Google Calendar...</p>
          ) : null}

          {!loading && viewMode === "month" ? (
            <>
              <div className="calendar-weekdays" aria-hidden>
                {weekdayLabels.map((day) => (
                  <div key={day}>{day}</div>
                ))}
              </div>

              <div
                className="calendar-grid"
                role="grid"
                aria-label="Calendar month grid"
              >
                {monthDays.map((day) => (
                  <button
                    key={dateKey(day.date)}
                    type="button"
                    role="gridcell"
                    aria-selected={day.isSelected}
                    className={`calendar-day ${day.inMonth ? "" : "outside"} ${day.isToday ? "today" : ""} ${day.isSelected ? "selected" : ""}`.trim()}
                    onClick={() => {
                      setSelectedDate(day.date);
                      if (!sameMonth(day.date, visibleMonth)) {
                        setVisibleMonth(startOfMonth(day.date));
                      }
                    }}
                  >
                    <span className="calendar-day-number">
                      {day.date.getDate()}
                    </span>
                    <span className="calendar-day-events">
                      {day.eventCount > 0
                        ? `${day.eventCount} event${day.eventCount === 1 ? "" : "s"}`
                        : ""}
                    </span>
                  </button>
                ))}
              </div>
            </>
          ) : null}

          {!loading && viewMode !== "month" ? (
            <div className={`calendar-board ${viewMode}-view`}>
              <div
                className={`schedule-head ${viewMode}-view`}
                style={{
                  gridTemplateColumns: scheduleTemplateColumns,
                }}
              >
                <div className="schedule-corner" />
                {visibleScheduleDays.map((day) => {
                  const isToday = sameDay(day, today);
                  const isSelected = sameDay(day, selectedDate);
                  return (
                    <button
                      key={`head-${dateKey(day)}`}
                      type="button"
                      className={`schedule-day-head ${isSelected ? "selected" : ""}`.trim()}
                      onClick={() => setSelectedDate(day)}
                    >
                      <span className="schedule-day-name">
                        {day.toLocaleDateString(undefined, {
                          weekday: viewMode === "day" ? "long" : "short",
                        })}
                      </span>
                      <span
                        className={`schedule-day-number ${isToday ? "today" : ""}`.trim()}
                      >
                        {day.getDate()}
                      </span>
                    </button>
                  );
                })}
              </div>

              <div
                className={`schedule-allday ${viewMode}-view`}
                style={{
                  gridTemplateColumns: scheduleTemplateColumns,
                }}
              >
                <div className="schedule-allday-label">All day</div>
                {allDayEventsByVisibleDay.map((items, index) => (
                  <div
                    key={`allday-${dateKey(visibleScheduleDays[index])}`}
                    className="schedule-allday-cell"
                  >
                    <div className="schedule-allday-events">
                      {items.slice(0, 3).map((event) => (
                        <button
                          key={event.id}
                          type="button"
                          className={`schedule-allday-pill tone-${event.tone}`}
                          onClick={() => openEventDetails(event)}
                        >
                          {event.title}
                        </button>
                      ))}
                    </div>
                  </div>
                ))}
              </div>

              <div className="schedule-scroll">
                <div
                  className={`schedule-grid ${viewMode}-view`}
                  style={{
                    gridTemplateColumns: scheduleTemplateColumns,
                    gridTemplateRows: `repeat(${totalScheduleSlots}, ${scheduleRowHeight}px)`,
                  }}
                >
                  {Array.from({ length: totalScheduleSlots }).map(
                    (_, slotIndex) => {
                      const slotHour =
                        scheduleStartHour + slotIndex / slotsPerHour;
                      return (
                        <div
                          key={`time-${slotIndex}`}
                          className="schedule-time"
                          style={{ gridColumn: 1, gridRow: slotIndex + 1 }}
                        >
                          {slotIndex % slotsPerHour === 0
                            ? formatTimeLabel(Math.floor(slotHour))
                            : ""}
                        </div>
                      );
                    },
                  )}

                  {visibleScheduleDays.flatMap((day, dayIndex) =>
                    Array.from({ length: totalScheduleSlots }).map(
                      (_, slotIndex) => (
                        <div
                          key={`cell-${dateKey(day)}-${slotIndex}`}
                          className="schedule-cell"
                          style={{
                            gridColumn: dayIndex + 2,
                            gridRow: slotIndex + 1,
                          }}
                        />
                      ),
                    ),
                  )}

                  {scheduleEvents.map((event) => (
                    <button
                      key={event.id}
                      type="button"
                      className={`schedule-event tone-${event.tone}`}
                      style={{
                        gridColumn: event.gridColumn,
                        gridRow: event.gridRow,
                      }}
                      onClick={() => openEventDetails(event)}
                    >
                      <h3>{event.title}</h3>
                      <p>{formatTimeRange(event.startsAt, event.endsAt)}</p>
                    </button>
                  ))}
                </div>
              </div>
            </div>
          ) : null}
        </section>

        <aside className="calendar-agenda" aria-label="Selected day agenda">
          <div className="agenda-header">
            <div>
              <h2>{formatSelectedLabel(selectedDate)}</h2>
              <p>{selectedDayEvents.length} scheduled</p>
            </div>
            <button
              type="button"
              className="agenda-add"
              aria-label="Add event"
              onClick={openEventForm}
            >
              <CalendarPlus size={14} />
            </button>
          </div>

          <div className="agenda-list">
            {selectedDayEvents.length === 0 ? (
              <p className="agenda-empty">
                No Google Calendar events for this date.
              </p>
            ) : (
              selectedDayEvents.map((event) => (
                <button
                  key={event.id}
                  type="button"
                  className={`agenda-item tone-${event.tone}`}
                  onClick={() => openEventDetails(event)}
                >
                  <h3>{event.title}</h3>
                  <p>
                    <Clock3 size={13} />
                    {formatTimeRange(
                      event.startsAt,
                      event.endsAt,
                      event.isAllDay,
                    )}
                  </p>
                  <p>
                    <MapPin size={13} />
                    {event.location}
                  </p>
                </button>
              ))
            )}
          </div>

          <div className="agenda-upcoming">
            <h3>Upcoming</h3>
            <div>
              {upcomingEvents.length === 0 ? (
                <p>
                  <strong>None</strong>
                  <span>No upcoming Google Calendar events in this range.</span>
                </p>
              ) : (
                upcomingEvents.map((event) => (
                  <button
                    key={`upcoming-${event.id}`}
                    type="button"
                    className="upcoming-item"
                    onClick={() => openEventDetails(event)}
                  >
                    <strong>
                      {event.startsAt.toLocaleDateString(undefined, {
                        month: "short",
                        day: "numeric",
                      })}
                    </strong>
                    <span>{event.title}</span>
                  </button>
                ))
              )}
            </div>
          </div>
        </aside>
      </main>

      <CalendarCreateEventDialog
        open={showEventForm}
        eventForm={eventForm}
        selectedDateKey={dateKey(selectedDate)}
        submitting={submittingEvent}
        onOpenChange={setShowEventForm}
        setEventForm={setEventForm}
        onSubmit={submitEvent}
      />

      <CalendarEventDetailsDialog
        event={selectedEvent}
        formatTimeRange={formatTimeRange}
        onOpenChange={(open) => {
          if (!open) {
            setSelectedEventId(null);
          }
        }}
        onDeleteRequest={() => setShowDeleteConfirm(true)}
      />

      <ConfirmDialog
        open={showDeleteConfirm}
        title="Delete this event?"
        body="This removes the event from your primary Google Calendar."
        confirmLabel="Delete event"
        busy={deletingEvent}
        onClose={() => setShowDeleteConfirm(false)}
        onConfirm={() => void deleteSelectedEvent()}
      />
    </>
  );
}
