# AGENTS.md

## Purpose
This file defines how code must be written in this repository.

## Core Engineering Rules
1. Keep code elegant, coherent, and aligned with the existing system structure.
2. Prefer object-oriented design: encapsulate behavior in focused classes with clear responsibilities.
3. Write the least code needed to solve the task correctly.
4. Do not add fallbacks, stubs, scaffolding branches, or placeholder paths.
5. Use built-in language/library capabilities first; avoid custom code when standard APIs already solve it.

## Evidence-First Implementation
1. Before implementing a non-trivial feature, review relevant tutorials, official docs, papers, or technical posts.
2. Implement only ideas that are traceable to those sources.
3. Record source links in docstrings, docs, or commit notes for each feature-level decision.
4. Prefer official documentation/tutorials over secondary summaries when both exist.

## Design and Code Quality
1. Keep interfaces small and explicit; avoid hidden behavior.
2. Keep naming consistent with domain terms used in the repository.
3. Remove dead code and duplicated logic instead of layering new wrappers over old code.
4. Fail directly on missing required config/inputs; do not add silent inference paths.
5. Keep public APIs stable unless a change is required and justified.

## Simplicity Constraints
1. No speculative abstractions.
2. No compatibility branches unless explicitly required.
3. No unused helper functions.
4. No custom implementation if a well-supported library feature exists.

## Implementation Checklist (Per Change)
1. Confirm scope and required behavior.
2. Check authoritative references for the feature.
3. Implement minimal coherent changes in existing architecture.
4. Remove now-redundant code.
5. Validate with the smallest meaningful runtime check.
6. Update docs/schema when behavior or interfaces change.
