# Frontend architecture (recorded as ADR-32 in docs/DECISIONS.md)

This note was written with the UI as its ADR-14; the project log numbers it ADR-32.

## Status
Accepted

## Context
ADR-12 originally selected Streamlit for the ClearGate user interface. However, Streamlit cannot reproduce the required enterprise visual fidelity, layout structure, and fine-grained interactive workflows (such as canvas bounding box review, localized span editing, and high-frequency polling states).

## Decision
Supersede the UI portion of ADR-12 with a dedicated React 18 + TypeScript + Vite single-page application styled using Tailwind CSS driven by semantic CSS variables.

The core architecture principle of ADR-12 remains strictly preserved:
The frontend is a completely thin client over the ClearGate FastAPI service. It holds zero privacy or gate decision logic, never infers or decides document safety client-side, and communicates strictly through the authenticated REST API contract.
