# AURA Architecture

## Product flow

```text
Browser Workspace <-> HTTP and WebSocket <-> Python application
                                                |
                                             Planner
                                                |
                                          Verification
                                                |
                                       Engineering Graph
                                                |
                                        Workspace events
```

The Engineering Workspace has four domain boundaries: Planner, Verification,
Engineering Graph, and Workspace. Infrastructure supplies model providers,
persistence, voice, registered tools, desktop actions, configuration, and
diagnostics without deciding engineering project state.

## Planner

`aura.planner` produces validated structured proposals and never commits graph
truth. The live adapter requests structured output from the configured AI
provider, makes one bounded repair attempt using exact validation errors, and
reports an honest deterministic fallback when the provider is unavailable or
invalid. Provider and model identity remain server-side operational metadata.

## Verification

`aura.verification` owns deterministic schema, reference, electrical, physical,
and safety checks. It assigns categorical states such as `tool_verified`,
`cross_checked`, `estimated`, `conceptual`, `stale`, `failed`, and
`unsupported`. These rules are not simulation or production certification.

## Engineering Graph

`aura.engineering_graph` owns entities, relationships, patches, revisions,
serialization, and deterministic lookup. It has no browser, QML, voice, model,
desktop, or Unreal dependency.

## Workspace

`aura.workspace` commits only accepted Verification output. Its FastAPI server
exposes project, graph, revision, modification, and replayable WebSocket event
APIs. The reusable browser frontend projects graph state; it does not invent a
second project model. Free-form edits follow the same boundary: AI produces a
graph patch proposal, Verification checks it, the user previews it, and only an
accepted proposal becomes a revision.

## Dependency rules

- Planner proposes but does not verify or commit.
- Verification transforms or rejects proposals but does not present them.
- Workspace commits verified patches and publishes semantic state changes.
- Voice may provide input or narration but cannot mutate graph state.
- Arbitrary shell execution is not supported.
- Server imports must not load QML, Torch, XTTS, or Unreal.

## Compatibility systems

The QML assistant, `AuraSupervisor`, desktop workflows, voice integrations,
Unreal domain, and historical specialist code remain optional compatibility
systems. Normal workspace startup does not import them.
