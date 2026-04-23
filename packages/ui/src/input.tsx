"use client";

import * as React from "react";

import { cn } from "./utils";

export type InputProps = React.InputHTMLAttributes<HTMLInputElement>;

export const Input = React.forwardRef<HTMLInputElement, InputProps>(
  ({ className, ...props }, ref) => (
    <input
      ref={ref}
      className={cn(
        "flex h-11 w-full rounded-[14px] border border-input bg-[color:var(--surface-1)] px-4 py-2 text-[0.92rem] text-[color:var(--text)] shadow-[inset_0_1px_0_rgba(255,255,255,0.75)] outline-none transition-[border-color,box-shadow,background-color] duration-150 ease-[var(--ease-out)] placeholder:text-[color:var(--text-subtle)] focus:border-[color:var(--line-emphasis)] focus:bg-white focus:shadow-[0_0_0_4px_var(--ring)] disabled:cursor-not-allowed disabled:opacity-50",
        className,
      )}
      {...props}
    />
  ),
);

Input.displayName = "Input";
