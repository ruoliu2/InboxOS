"use client";

import { type Dispatch, type FormEvent, type SetStateAction } from "react";
import { MapPin, Trash2 } from "lucide-react";

import { Button } from "@inboxos/ui/button";
import { Dialog, DialogContent } from "@inboxos/ui/dialog";
import { Input } from "@inboxos/ui/input";
import { Textarea } from "@inboxos/ui/textarea";

type EventFormState = {
  title: string;
  startsAt: string;
  endsAt: string;
  location: string;
  description: string;
  isAllDay: boolean;
};

type CalendarEventDetails = {
  id: string;
  title: string;
  startsAt: Date;
  endsAt: Date;
  location: string;
  description: string;
  isAllDay: boolean;
  htmlLink: string | null;
  canDelete: boolean;
};

type CalendarCreateEventDialogProps = {
  open: boolean;
  eventForm: EventFormState;
  selectedDateKey: string;
  submitting: boolean;
  onOpenChange: (open: boolean) => void;
  setEventForm: Dispatch<SetStateAction<EventFormState>>;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
};

type CalendarEventDetailsDialogProps = {
  event: CalendarEventDetails | null;
  formatTimeRange: (start: Date, end: Date, isAllDay?: boolean) => string;
  onOpenChange: (open: boolean) => void;
  onDeleteRequest: () => void;
};

const fieldClass =
  "rounded-[12px] border-[var(--line)] bg-white text-[0.9rem] shadow-none";

export function CalendarCreateEventDialog({
  open,
  eventForm,
  selectedDateKey,
  submitting,
  onOpenChange,
  setEventForm,
  onSubmit,
}: CalendarCreateEventDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        aria-label="Create calendar event"
        className="w-[min(560px,calc(100vw-24px))] rounded-[18px] border-[var(--line)] bg-white p-0 shadow-[0_18px_44px_rgba(15,23,42,0.12)]"
      >
        <div className="border-b border-[var(--line)] px-6 py-5">
          <h2 className="m-0 text-[1.05rem] font-semibold text-[var(--text)]">
            Create event
          </h2>
          <p className="mt-1 text-[0.86rem] text-[var(--muted)]">
            Add an event to your primary Google Calendar.
          </p>
        </div>
        <form className="grid gap-4 px-6 py-5" onSubmit={onSubmit}>
          <Input
            value={eventForm.title}
            onChange={(event) =>
              setEventForm((current) => ({
                ...current,
                title: event.target.value,
              }))
            }
            placeholder="Event title"
            aria-label="Event title"
            className={fieldClass}
          />
          <label className="flex items-center gap-2 text-[0.87rem] font-medium text-[var(--text)]">
            <input
              type="checkbox"
              className="h-4 w-4 rounded border-[var(--line-strong)]"
              checked={eventForm.isAllDay}
              onChange={(event) =>
                setEventForm((current) => ({
                  ...current,
                  isAllDay: event.target.checked,
                  startsAt: event.target.checked
                    ? selectedDateKey
                    : current.startsAt,
                  endsAt: event.target.checked
                    ? selectedDateKey
                    : current.endsAt,
                }))
              }
            />
            All day
          </label>
          <div className="grid gap-3 sm:grid-cols-2">
            <Input
              type={eventForm.isAllDay ? "date" : "datetime-local"}
              value={eventForm.startsAt}
              onChange={(event) =>
                setEventForm((current) => ({
                  ...current,
                  startsAt: event.target.value,
                }))
              }
              aria-label={eventForm.isAllDay ? "Start date" : "Start time"}
              className={fieldClass}
            />
            <Input
              type={eventForm.isAllDay ? "date" : "datetime-local"}
              value={eventForm.endsAt}
              onChange={(event) =>
                setEventForm((current) => ({
                  ...current,
                  endsAt: event.target.value,
                }))
              }
              aria-label={eventForm.isAllDay ? "End date" : "End time"}
              className={fieldClass}
            />
          </div>
          <Input
            value={eventForm.location}
            onChange={(event) =>
              setEventForm((current) => ({
                ...current,
                location: event.target.value,
              }))
            }
            placeholder="Location"
            aria-label="Event location"
            className={fieldClass}
          />
          <Textarea
            value={eventForm.description}
            onChange={(event) =>
              setEventForm((current) => ({
                ...current,
                description: event.target.value,
              }))
            }
            placeholder="Description"
            aria-label="Event description"
            className="min-h-[120px] rounded-[12px] border-[var(--line)] bg-white text-[0.9rem] shadow-none"
          />
          <div className="flex justify-end gap-2 pt-1">
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={submitting}>
              {submitting ? "Creating..." : "Create event"}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function CalendarEventDetailsDialog({
  event,
  formatTimeRange,
  onOpenChange,
  onDeleteRequest,
}: CalendarEventDetailsDialogProps) {
  return (
    <Dialog open={event !== null} onOpenChange={onOpenChange}>
      <DialogContent
        aria-label="Calendar event details"
        className="w-[min(560px,calc(100vw-24px))] rounded-[18px] border-[var(--line)] bg-white p-0 shadow-[0_18px_44px_rgba(15,23,42,0.12)]"
      >
        {event ? (
          <>
            <div className="border-b border-[var(--line)] px-6 py-5">
              <h2 className="m-0 text-[1.05rem] font-semibold text-[var(--text)]">
                {event.title}
              </h2>
              <p className="mt-1 text-[0.86rem] text-[var(--muted)]">
                {formatTimeRange(event.startsAt, event.endsAt, event.isAllDay)}
              </p>
            </div>
            <div className="grid gap-4 px-6 py-5 text-[0.9rem] text-[var(--text)]">
              <p className="m-0 flex items-start gap-2">
                <MapPin
                  size={14}
                  className="mt-0.5 shrink-0 text-[var(--muted)]"
                />
                <span>{event.location}</span>
              </p>
              {event.description ? (
                <p className="m-0 whitespace-pre-wrap text-[var(--muted)]">
                  {event.description}
                </p>
              ) : null}
              {event.htmlLink ? (
                <a
                  href={event.htmlLink}
                  target="_blank"
                  rel="noreferrer"
                  className="text-[0.86rem] font-medium text-[#2563eb] hover:underline"
                >
                  Open in Google Calendar
                </a>
              ) : null}
            </div>
            <div className="flex justify-between gap-2 border-t border-[var(--line)] px-6 py-4">
              <div>
                {event.canDelete ? (
                  <Button
                    type="button"
                    variant="outline"
                    className="border-[#fecdd3] text-[#be123c] hover:bg-[#fff1f2]"
                    onClick={onDeleteRequest}
                  >
                    <Trash2 size={14} />
                    Delete event
                  </Button>
                ) : null}
              </div>
              <Button
                type="button"
                variant="outline"
                onClick={() => onOpenChange(false)}
              >
                Close
              </Button>
            </div>
          </>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}
