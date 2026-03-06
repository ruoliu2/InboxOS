"use client";

import { useMemo, useState } from "react";
import {
  CalendarPlus,
  ChevronLeft,
  ChevronRight,
  Clock3,
  MapPin,
} from "lucide-react";

type ViewMode = "day" | "week" | "month";

type CalendarEvent = {
  id: string;
  title: string;
  startsAt: Date;
  endsAt: Date;
  location: string;
  tone: "blue" | "green" | "amber" | "rose";
};

const calendarViews: ViewMode[] = ["day", "week", "month"];
const weekdayLabels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const scheduleStartHour = 0;
const scheduleEndHour = 24;
const slotsPerHour = 2;
const scheduleSlotMinutes = 60 / slotsPerHour;
const scheduleRowHeight = 34;
const totalScheduleSlots = (scheduleEndHour - scheduleStartHour) * slotsPerHour;

const seedDate = new Date();
const seedYear = seedDate.getFullYear();
const seedMonth = seedDate.getMonth();

const demoEvents: CalendarEvent[] = [
  {
    id: "e-1",
    title: "Team Sync",
    startsAt: new Date(seedYear, seedMonth, 4, 9, 0),
    endsAt: new Date(seedYear, seedMonth, 4, 9, 45),
    location: "HQ - Room Polaris",
    tone: "blue",
  },
  {
    id: "e-2",
    title: "Design Critique",
    startsAt: new Date(seedYear, seedMonth, 4, 13, 30),
    endsAt: new Date(seedYear, seedMonth, 4, 14, 30),
    location: "Figma Review",
    tone: "green",
  },
  {
    id: "e-3",
    title: "Product Roadmap",
    startsAt: new Date(seedYear, seedMonth, 6, 10, 0),
    endsAt: new Date(seedYear, seedMonth, 6, 11, 30),
    location: "Zoom",
    tone: "amber",
  },
  {
    id: "e-4",
    title: "1:1 with PM",
    startsAt: new Date(seedYear, seedMonth, 9, 15, 0),
    endsAt: new Date(seedYear, seedMonth, 9, 15, 30),
    location: "Cafe Atrium",
    tone: "rose",
  },
  {
    id: "e-5",
    title: "Release Readiness",
    startsAt: new Date(seedYear, seedMonth, 12, 11, 0),
    endsAt: new Date(seedYear, seedMonth, 12, 12, 0),
    location: "Ops War Room",
    tone: "blue",
  },
  {
    id: "e-6",
    title: "Customer Demo",
    startsAt: new Date(seedYear, seedMonth, 15, 16, 0),
    endsAt: new Date(seedYear, seedMonth, 15, 17, 0),
    location: "Client Portal",
    tone: "green",
  },
  {
    id: "e-7",
    title: "Sprint Planning",
    startsAt: new Date(seedYear, seedMonth, 20, 9, 30),
    endsAt: new Date(seedYear, seedMonth, 20, 11, 0),
    location: "Board Room",
    tone: "amber",
  },
  {
    id: "e-8",
    title: "Marketing Launch",
    startsAt: new Date(seedYear, seedMonth, 23, 14, 0),
    endsAt: new Date(seedYear, seedMonth, 23, 15, 0),
    location: "Launch Standup",
    tone: "rose",
  },
];

function dateKey(value: Date): string {
  const y = value.getFullYear();
  const m = String(value.getMonth() + 1).padStart(2, "0");
  const d = String(value.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
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

function formatTimeRange(start: Date, end: Date): string {
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

export function CalendarWorkspace() {
  const [viewMode, setViewMode] = useState<ViewMode>("week");
  const [visibleMonth, setVisibleMonth] = useState<Date>(
    startOfMonth(seedDate),
  );
  const [selectedDate, setSelectedDate] = useState<Date>(new Date(seedDate));

  const eventsByDay = useMemo(() => {
    const map = new Map<string, CalendarEvent[]>();

    for (const event of demoEvents) {
      const key = dateKey(event.startsAt);
      const current = map.get(key) ?? [];
      current.push(event);
      current.sort((a, b) => a.startsAt.getTime() - b.startsAt.getTime());
      map.set(key, current);
    }

    return map;
  }, []);

  const monthDays = useMemo(() => {
    const first = startOfMonth(visibleMonth);
    const mondayOffset = (first.getDay() + 6) % 7;
    const gridStart = addDays(first, -mondayOffset);

    return Array.from({ length: 42 }, (_, index) => {
      const date = addDays(gridStart, index);
      return {
        date,
        inMonth: date.getMonth() === visibleMonth.getMonth(),
        isToday: sameDay(date, seedDate),
        isSelected: sameDay(date, selectedDate),
        eventCount: (eventsByDay.get(dateKey(date)) ?? []).length,
      };
    });
  }, [eventsByDay, selectedDate, visibleMonth]);

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
    return demoEvents
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
  }, [visibleScheduleDays]);

  const upcomingEvents = useMemo(() => {
    return [...demoEvents]
      .filter((event) => event.startsAt.getTime() >= selectedDate.getTime())
      .sort((a, b) => a.startsAt.getTime() - b.startsAt.getTime())
      .slice(0, 4);
  }, [selectedDate]);

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
    const today = new Date();
    setVisibleMonth(startOfMonth(today));
    setSelectedDate(today);
  }

  function changeView(nextView: ViewMode) {
    setViewMode(nextView);
    if (nextView === "month") {
      setVisibleMonth(startOfMonth(selectedDate));
    }
  }

  return (
    <main className="calendar-shell panel-surface">
      <section className="calendar-main">
        <div className="calendar-title-row">
          <div className="calendar-title-copy">
            <h1>{formatViewTitle(viewMode, selectedDate, visibleMonth)}</h1>
            <p>
              Day, week, and month views based on the macOS calendar layout in
              docs.
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

        {viewMode === "month" ? (
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
        ) : (
          <div className={`calendar-board ${viewMode}-view`}>
            <div
              className={`schedule-head ${viewMode}-view`}
              style={{
                gridTemplateColumns: scheduleTemplateColumns,
              }}
            >
              <div className="schedule-corner" />
              {visibleScheduleDays.map((day) => {
                const isToday = sameDay(day, seedDate);
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
              {visibleScheduleDays.map((day) => (
                <div
                  key={`allday-${dateKey(day)}`}
                  className="schedule-allday-cell"
                />
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
                  <article
                    key={event.id}
                    className={`schedule-event tone-${event.tone}`}
                    style={{
                      gridColumn: event.gridColumn,
                      gridRow: event.gridRow,
                    }}
                  >
                    <h3>{event.title}</h3>
                    <p>{formatTimeRange(event.startsAt, event.endsAt)}</p>
                  </article>
                ))}
              </div>
            </div>
          </div>
        )}
      </section>

      <aside className="calendar-agenda" aria-label="Selected day agenda">
        <div className="agenda-header">
          <div>
            <h2>{formatSelectedLabel(selectedDate)}</h2>
            <p>{selectedDayEvents.length} scheduled</p>
          </div>
          <button type="button" className="agenda-add" aria-label="Add event">
            <CalendarPlus size={14} />
          </button>
        </div>

        <div className="agenda-list">
          {selectedDayEvents.length === 0 ? (
            <p className="agenda-empty">No events for this date.</p>
          ) : (
            selectedDayEvents.map((event) => (
              <article
                key={event.id}
                className={`agenda-item tone-${event.tone}`}
              >
                <h3>{event.title}</h3>
                <p>
                  <Clock3 size={13} />
                  {formatTimeRange(event.startsAt, event.endsAt)}
                </p>
                <p>
                  <MapPin size={13} />
                  {event.location}
                </p>
              </article>
            ))
          )}
        </div>

        <div className="agenda-upcoming">
          <h3>Upcoming</h3>
          <div>
            {upcomingEvents.map((event) => (
              <p key={`upcoming-${event.id}`}>
                <strong>
                  {event.startsAt.toLocaleDateString(undefined, {
                    month: "short",
                    day: "numeric",
                  })}
                </strong>
                <span>{event.title}</span>
              </p>
            ))}
          </div>
        </div>
      </aside>
    </main>
  );
}
