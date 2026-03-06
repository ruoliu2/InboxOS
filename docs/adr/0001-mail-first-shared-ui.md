# ADR 0001: Mail First Shared UI

## Status

Accepted

## Decision

The product uses a mail-first UI as the primary surface, with the web app defining the shared interface and future macOS packaging expected to preserve the same experience.

## Why

- the mail workflow is the core product value
- users benefit from a familiar three-pane mental model
- keeping the surface narrow reduces UI sprawl while the MVP is still being hardened

## Consequences

- `/mail` is the primary route
- tasks and calendar are secondary surfaces
- the design system and layout decisions should optimize for the mail workflow first
