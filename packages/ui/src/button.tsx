"use client";

import * as React from "react";

import { cn } from "./utils";

const BUTTON_BASE =
  "inline-flex items-center justify-center rounded-full text-[0.82rem] font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#94a3b8] focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50";

const BUTTON_VARIANTS = {
  default: "border border-[#111827] bg-[#111827] text-white hover:bg-black",
  outline: "border border-[#e5e7eb] bg-white text-[#111827] hover:bg-[#f8fafc]",
  ghost:
    "border border-transparent bg-transparent text-[#111827] hover:bg-[#f4f4f5]",
} as const;

const BUTTON_SIZES = {
  default: "min-h-7 px-3 py-1.5",
  icon: "h-7 w-7 p-0",
  pill: "min-h-7 px-2.5 py-1.5",
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
