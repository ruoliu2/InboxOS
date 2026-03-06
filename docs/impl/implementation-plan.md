# Implementation Plan

This document captures the intended implementation sequence for the current MVP.

## Phase 1: Shared Mail First Surface

- keep `packages/app`, `packages/features`, and `packages/ui` as the shared UI source of truth
- stabilize the mail three-pane workspace first
- keep tasks and calendar secondary to the mail workflow

## Phase 2: Thread And Task Core

- harden thread sync and thread analysis in `apps/api`
- keep direct reply flow inside the mail workspace
- keep task derivation from analyzed threads reliable

## Phase 3: Desktop Shell Readiness

- keep `apps/desktop` thin while the shared packages stabilize
- avoid forking UI logic out of the shared packages
- prepare desktop-specific bridges only where the shell truly needs them

## Phase 4: Deployment And Operational Readiness

- deploy `apps/web` on Vercel
- deploy `apps/api` on Railway
- validate environment setup and cross-surface behavior

## Ongoing Constraints

- keep the product mail-first
- keep the live API contract small and coherent
- avoid dashboard-style drift
- preserve a clean path for future macOS packaging
