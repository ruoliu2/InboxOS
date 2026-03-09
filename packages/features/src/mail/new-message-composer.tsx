"use client";

import { type ChangeEvent, useEffect, useRef } from "react";
import { ChevronDown, Clock, Paperclip, Send, X } from "lucide-react";

import { Button } from "@inboxos/ui/button";
import { Dialog, DialogContent } from "@inboxos/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@inboxos/ui/dropdown-menu";
import { Input } from "@inboxos/ui/input";
import { Textarea } from "@inboxos/ui/textarea";
import { cn } from "@inboxos/ui/utils";

export type NewMessageAttachment = {
  id: string;
  file: File;
  previewUrl: string;
};

type NewMessageComposerProps = {
  open: boolean;
  sending: boolean;
  minimized: boolean;
  maximized: boolean;
  scheduleMenuOpen: boolean;
  to: string;
  subject: string;
  body: string;
  attachments: NewMessageAttachment[];
  accountLabel: string;
  accountEmail?: string | null;
  canSend: boolean;
  onOpenChange: (open: boolean) => void;
  onToggleMinimized: () => void;
  onToggleMaximized: () => void;
  onScheduleMenuOpenChange: (open: boolean) => void;
  onToChange: (value: string) => void;
  onSubjectChange: (value: string) => void;
  onBodyChange: (value: string) => void;
  onAttachmentsChange: (event: ChangeEvent<HTMLInputElement>) => void;
  onRemoveAttachment: (attachmentId: string) => void;
  onSend: () => void;
  onScheduleAtEight: () => void;
};

const topbarButtonClass = "h-7 gap-1.5 border-[#e5e7eb] px-2.5 text-[0.82rem]";
const rowClass =
  "grid h-11 grid-cols-[78px_minmax(0,1fr)] items-center gap-2.5 border-b border-[#ececec] px-[22px] max-[960px]:grid-cols-1 max-[960px]:gap-1 max-[960px]:py-2";
const labelClass = "text-[0.83rem] text-[#7c7c7c]";

function formatAttachmentSize(size: number): string {
  if (size < 1024) {
    return `${size} B`;
  }
  if (size < 1024 * 1024) {
    return `${Math.round(size / 1024)} KB`;
  }
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

export function NewMessageComposer({
  open,
  sending,
  minimized,
  maximized,
  scheduleMenuOpen,
  to,
  subject,
  body,
  attachments,
  accountLabel,
  accountEmail,
  canSend,
  onOpenChange,
  onToggleMinimized,
  onToggleMaximized,
  onScheduleMenuOpenChange,
  onToChange,
  onSubjectChange,
  onBodyChange,
  onAttachmentsChange,
  onRemoveAttachment,
  onSend,
  onScheduleAtEight,
}: NewMessageComposerProps) {
  const toInputRef = useRef<HTMLInputElement | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    if (!open) {
      return;
    }

    const frame = window.requestAnimationFrame(() => {
      toInputRef.current?.focus();
    });
    return () => {
      window.cancelAnimationFrame(frame);
    };
  }, [open]);

  useEffect(() => {
    if (attachments.length === 0 && fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  }, [attachments.length]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        aria-label="New email composer"
        onEscapeKeyDown={(event: Event) => {
          if (sending) {
            event.preventDefault();
          }
        }}
        onPointerDownOutside={(event: Event) => {
          if (sending) {
            event.preventDefault();
          }
        }}
        className={cn(
          "w-[min(980px,calc(100vw-40px))] max-w-[calc(100vw-24px)] min-w-[760px] resize overflow-hidden rounded-[16px] border-[#e5e7eb] bg-white p-0 shadow-[0_8px_20px_rgba(2,6,23,0.05)] max-[960px]:h-[min(calc(100vh-20px),720px)] max-[960px]:w-[min(840px,calc(100vw-20px))] max-[960px]:min-h-0 max-[960px]:min-w-0 max-[960px]:resize-none",
          maximized
            ? "h-[calc(100vh-24px)] w-[calc(100vw-24px)] max-h-[calc(100vh-24px)] max-w-[calc(100vw-24px)]"
            : minimized
              ? "h-auto resize-x"
              : "h-[min(620px,calc(100vh-40px))] max-h-[calc(100vh-24px)]",
        )}
      >
        <div className="flex h-full min-h-0 flex-col">
          <div className="grid h-11 grid-cols-[auto_1fr_auto] items-center gap-3 border-b border-[#e5e7eb] bg-white px-4 max-[960px]:grid-cols-1 max-[960px]:justify-items-start">
            <div className="flex items-center gap-2">
              <button
                type="button"
                className="h-3 w-3 rounded-full bg-[#ff5f57] p-0 disabled:cursor-not-allowed disabled:opacity-70"
                aria-label="Close composer"
                onClick={() => onOpenChange(false)}
                disabled={sending}
              />
              <button
                type="button"
                className="h-3 w-3 rounded-full bg-[#febc2e] p-0"
                aria-label={minimized ? "Expand composer" : "Minimize composer"}
                onClick={onToggleMinimized}
              />
              <button
                type="button"
                className="h-3 w-3 rounded-full bg-[#28c840] p-0"
                aria-label={
                  maximized ? "Restore composer size" : "Expand composer size"
                }
                onClick={onToggleMaximized}
              />
            </div>

            <div className="flex items-center justify-center gap-2.5 max-[960px]:flex-wrap max-[960px]:justify-start">
              <Button
                variant="outline"
                size="pill"
                className={topbarButtonClass}
                onClick={() => fileInputRef.current?.click()}
                aria-label="Attach files"
                title="Attach files"
              >
                <Paperclip size={14} />
              </Button>
              <DropdownMenu
                open={scheduleMenuOpen}
                onOpenChange={onScheduleMenuOpenChange}
              >
                <DropdownMenuTrigger asChild>
                  <Button
                    variant="outline"
                    size="pill"
                    className={topbarButtonClass}
                    aria-label="Schedule send"
                    title="Schedule send"
                  >
                    <Clock size={14} />
                    <ChevronDown size={14} />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuItem
                    onSelect={() => {
                      onSend();
                    }}
                  >
                    Send now
                  </DropdownMenuItem>
                  <DropdownMenuItem onSelect={onScheduleAtEight}>
                    Send at 8:00 am
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
              <input
                ref={fileInputRef}
                type="file"
                accept="image/*"
                multiple
                hidden
                onChange={onAttachmentsChange}
              />
            </div>

            <div className="flex items-center justify-end gap-2 max-[960px]:justify-start">
              <Button
                variant="default"
                size="pill"
                className="h-7 min-w-[34px] px-2.5"
                onClick={onSend}
                disabled={!canSend}
                aria-label={sending ? "Sending" : "Send"}
                title={sending ? "Sending" : "Send"}
              >
                <Send size={15} />
              </Button>
            </div>
          </div>

          {!minimized ? (
            <div className="flex min-h-0 flex-1 flex-col">
              <div className="grid grid-rows-3">
                <label className={rowClass}>
                  <span className={labelClass}>To:</span>
                  <Input
                    ref={toInputRef}
                    value={to}
                    onChange={(event) => onToChange(event.target.value)}
                    aria-label="Message recipients"
                    className="h-auto border-0 p-0 text-[0.86rem] shadow-none focus-visible:ring-0"
                  />
                </label>
                <label className={rowClass}>
                  <span className={labelClass}>Subject:</span>
                  <Input
                    value={subject}
                    onChange={(event) => onSubjectChange(event.target.value)}
                    aria-label="Message subject"
                    className="h-auto border-0 p-0 text-[0.86rem] shadow-none focus-visible:ring-0"
                  />
                </label>
                <div className={cn(rowClass, "text-[#3f3f46]")}>
                  <span className={labelClass}>From:</span>
                  <div className="min-w-0 truncate text-[0.86rem]">
                    {accountLabel}
                    {accountEmail ? ` - ${accountEmail}` : ""}
                  </div>
                </div>
              </div>

              {attachments.length > 0 ? (
                <div
                  className="grid max-h-36 flex-none grid-cols-[repeat(auto-fit,minmax(220px,1fr))] gap-2 overflow-auto border-b border-[#ececec] bg-white px-[22px] py-3"
                  aria-label="Selected image attachments"
                >
                  {attachments.map((attachment) => (
                    <article
                      key={attachment.id}
                      className="grid grid-cols-[48px_minmax(0,1fr)_auto] items-center gap-2.5 rounded-[10px] border border-[var(--line)] bg-[#fafafa] p-2"
                    >
                      <img
                        src={attachment.previewUrl}
                        alt={attachment.file.name}
                        className="h-12 w-12 rounded-[8px] bg-[#e5e7eb] object-cover"
                      />
                      <div className="grid min-w-0 gap-[3px]">
                        <strong
                          title={attachment.file.name}
                          className="truncate text-[0.82rem]"
                        >
                          {attachment.file.name}
                        </strong>
                        <span className="truncate text-[0.75rem] text-[var(--muted)]">
                          {formatAttachmentSize(attachment.file.size)}
                        </span>
                      </div>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-7 w-7 rounded-[8px]"
                        aria-label={`Remove ${attachment.file.name}`}
                        onClick={() => onRemoveAttachment(attachment.id)}
                      >
                        <X size={14} />
                      </Button>
                    </article>
                  ))}
                </div>
              ) : null}

              <div className="min-h-0 flex-1">
                <Textarea
                  value={body}
                  onChange={(event) => onBodyChange(event.target.value)}
                  aria-label="Message body"
                  className="h-full min-h-full resize-none rounded-none border-0 px-[22px] pb-6 pt-[18px] text-[0.92rem] leading-[1.5] shadow-none focus-visible:ring-0"
                />
              </div>
            </div>
          ) : null}
        </div>
      </DialogContent>
    </Dialog>
  );
}
