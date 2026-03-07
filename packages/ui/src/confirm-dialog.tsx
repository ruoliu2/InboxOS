"use client";

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
  if (!open) {
    return null;
  }

  return (
    <div className="overlay-backdrop" onClick={onClose} role="presentation">
      <div
        className="overlay-card confirm-dialog"
        onClick={(event) => event.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby="confirm-dialog-title"
      >
        <div className="overlay-copy">
          <h2 id="confirm-dialog-title">{title}</h2>
          <p>{body}</p>
        </div>
        <div className="overlay-actions">
          <button type="button" onClick={onClose} disabled={busy}>
            {cancelLabel}
          </button>
          <button
            type="button"
            className={confirmTone === "danger" ? "btn-danger" : "btn-primary"}
            onClick={onConfirm}
            disabled={busy}
          >
            {busy ? "Working..." : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
