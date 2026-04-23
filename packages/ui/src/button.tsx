"use client";

import * as React from "react";

import { cn } from "./utils";

const BUTTON_BASE =
  "inline-flex items-center justify-center gap-2 rounded-[14px] text-[0.82rem] font-semibold tracking-[-0.01em] transition-[transform,background-color,border-color,color,box-shadow,opacity] duration-150 ease-[var(--ease-out)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--ring)] focus-visible:ring-offset-2 focus-visible:ring-offset-[color:var(--surface-0)] active:scale-[0.98] disabled:pointer-events-none disabled:opacity-50";

const BUTTON_VARIANTS = {
  default:
    "border border-[color:var(--accent-strong)] bg-[color:var(--accent-strong)] text-white shadow-[0_16px_32px_rgba(37,99,235,0.24)] hover:border-[color:var(--accent)] hover:bg-[color:var(--accent)]",
  outline:
    "border border-[color:var(--line-strong)] bg-[color:var(--surface-1)] text-[color:var(--text)] shadow-[0_10px_24px_rgba(15,23,42,0.08)] hover:border-[color:var(--line-emphasis)] hover:bg-[color:var(--surface-2)]",
  ghost:
    "border border-transparent bg-transparent text-[color:var(--text-muted)] hover:bg-[color:var(--surface-2)] hover:text-[color:var(--text)]",
} as const;

const BUTTON_SIZES = {
  default: "min-h-10 px-4 py-2.5",
  icon: "h-10 w-10 p-0",
  pill: "min-h-9 rounded-full px-3.5 py-2",
} as const;

type ButtonVariant = keyof typeof BUTTON_VARIANTS;
type ButtonSize = keyof typeof BUTTON_SIZES;

export type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  size?: ButtonSize;
};

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  (
    {
      className,
      variant = "default",
      size = "default",
      type = "button",
      ...props
    },
    ref,
  ) => (
    <button
      ref={ref}
      type={type}
      className={cn(
        BUTTON_BASE,
        BUTTON_VARIANTS[variant],
        BUTTON_SIZES[size],
        className,
      )}
      {...props}
    />
  ),
);

Button.displayName = "Button";
