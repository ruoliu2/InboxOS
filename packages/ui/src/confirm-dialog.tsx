"use client";

import { Button } from "./button";
import { Dialog, DialogContent } from "./dialog";

type ConfirmDialogProps = {
  open: boolean;
  title: string;
  body: string;
  confirmLabel?: string;
  cancelLabel?: string;
  confirmTone?: "primary" | "danger";
  busy?: boolean;
  onClose: () => void;
  onConfirm: () => void;
};

export function ConfirmDialog({
  open,
  title,
  body,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  confirmTone = "danger",
  busy = false,
  onClose,
  onConfirm,
}: ConfirmDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onClose}>
      <DialogContent
        aria-labelledby="confirm-dialog-title"
        className="w-[min(420px,calc(100vw-24px))] rounded-[18px] border-[var(--line)] bg-white p-0 shadow-[0_18px_44px_rgba(15,23,42,0.12)]"
      >
        <div className="border-b border-[var(--line)] px-6 py-5">
          <h2
            id="confirm-dialog-title"
            className="m-0 text-[1.02rem] font-semibold text-[var(--text)]"
          >
            {title}
          </h2>
          <p className="mt-1 text-[0.86rem] text-[var(--muted)]">{body}</p>
        </div>
        <div className="flex justify-end gap-2 px-6 py-4">
          <Button
            type="button"
            variant="outline"
            onClick={onClose}
            disabled={busy}
          >
            {cancelLabel}
          </Button>
          <Button
            type="button"
            variant={confirmTone === "danger" ? "outline" : "default"}
            className={
              confirmTone === "danger"
                ? "border-[#fecdd3] text-[#be123c] hover:bg-[#fff1f2]"
                : undefined
            }
            onClick={onConfirm}
            disabled={busy}
          >
            {busy ? "Working..." : confirmLabel}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
