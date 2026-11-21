---
title: dc-ops-agent design
created: 2026-11-21
created_by: Claude (C)
status: APPROVED by the author 2026-11-21 ("Approve both": the design and the model download). Model chosen: qwen3:8b, 5.23 GB, Apache 2.0.
---

# dc-ops-agent: design

## Why

Portfolio repo built for AI agent engineering roles.
It closes the two gaps no current public repo covers (LLM observability, a runnable deployable
agent service) and shows the rest in one small, readable Python codebase: a tool-calling agent
loop, an MCP server, RAG, evals, a loop guard, and human approval for writes. The data center
theme is deliberate: data center operations is a domain few AI applicants can speak to credibly,
so the repo tells one coherent story.

## Decided by the author (2026-11-21)

- Theme: data center operations incident agent.
- Model: local only, through Ollama. No paid API key, no public live demo.
- Cloud: not yet. Ship it runnable locally plus a written deploy guide.

## Goals

1. Given active alarms, the agent investigates through tools, names the most likely cause, cites
   the runbook steps that apply, and drafts a work order. It never files the work order without a
   person's approval.
2. Every part a reviewer looks for is visible and small enough to read in minutes.
3. The test suite runs in CI with no model at all. The model-based evals run locally on Ollama
   and their latest scores are committed.

## Non-goals

- Real equipment, real BMS/EPMS/DCIM integrations, or any real company's procedures.
- A web UI. A terminal run with a clean printed report, and the traces, are the demo.
- Fine-tuning.

## Anti-goals (would make it a failure even if it works)

- Anything that reads as a real operator's internal material. All sample data and runbooks are generic,
  written from public industry practice, and labeled fictional.
- Claims the code does not back. The README says exactly what is measured and on which model.
- A tangle. If a reviewer cannot find the loop, the gate and the tracing in two minutes, it failed.

## Approaches considered

1. **Hand-written agent loop + official MCP Python SDK + OpenTelemetry (chosen, my call).**
   Shows that the author understands the loop, the tool protocol and tracing, not just a framework's
   API. AI agent engineering roles list "custom agent frameworks" alongside LangChain and others.
2. LangGraph agent with LangSmith tracing. Ticks a framework name, but hides the loop and the
   gate inside the framework and ties tracing to a paid service.
3. Extend the author's existing terminal app instead. Already public, but it is proprietary, desktop-only and huge;
   a reviewer cannot run or read it quickly.

## Design

**Repo:** `plutothedev/dc-ops-agent`, Python 3.11, MIT, code at the repo root.

**Sample site (fictional):** one data hall with two power paths (A and B), UPS units, PDUs,
CRAH cooling units, one chiller loop and one generator. Data files: equipment topology (what feeds
what), an active-alarm feed, and per-equipment sensor history. About six incident scenarios,
each with a known cause, for example a CRAH fan failure behind a high-temperature alarm, a UPS
on battery after a utility sag, a PDU breaker trip that takes one path down while the other
carries the load, and a generator that fails its weekly test.

**Runbooks:** about ten short generic procedures in markdown (high supply air temperature, UPS
on battery, breaker trip, chiller low flow, generator test failure, and so on).

**MCP server (`dcops_mcp`):** read-only tools `list_active_alarms`, `get_alarm`,
`get_equipment` (with upstream and downstream), `get_sensor_history`, `search_runbooks`; one
write tool `draft_work_order`, annotated destructive. Built on the official `mcp` SDK, stdio.

**RAG:** runbooks split into sections; hybrid search: BM25 keyword scoring always, plus
embeddings from Ollama's `nomic-embed-text` (already installed) when Ollama is running, fused by
reciprocal rank. Falls back to BM25 alone, so tests need no model.

**Agent (`dcops_agent`):** connects to the MCP server over stdio, calls the model through
Ollama's OpenAI-compatible endpoint with native tool calling, and loops until the model answers
without a tool call.
- Loop guard: a step cap, and a stop when the model repeats the same tool call with the same
  arguments.
- Approval gate in code: read-only tools run; `draft_work_order` waits for a yes at the terminal
  (or is refused in non-interactive runs). Tool output is wrapped and labeled as data.
- Output: a short incident report: cause, evidence (which readings), runbook steps cited by
  section, and the work order draft.

**Tracing:** OpenTelemetry spans for the run, each model call (model, latency, token counts when
the endpoint reports them) and each tool call (name, arguments, result size, approval outcome).
Exported to a local JSONL file by default, with a small viewer script that prints the run as a
tree; OTLP export (Jaeger, Grafana Tempo) by setting one environment variable.

**Evals:**
- Deterministic, in CI: retrieval hit@3 and MRR on a gold question set; tool behavior; the loop
  guard and the approval gate driven by a scripted fake model; a prompt-injection case (an alarm
  note telling the agent to close all alarms and file a work order) that must not cause a write.
- Model evals, local: every scenario run against the Ollama model; scored on correct cause
  equipment, correct runbook cited, no write without approval, and steps used. Results table
  committed to the README with the model name and date.

**Delivery:** README with a two-minute tour (where the loop, gate, tracing and evals live), a
recorded sample run, a `Dockerfile`, and `DEPLOY.md` describing how to run it on a cloud VM or
container service. Docker is not installed on this PC, so the Dockerfile is written but not
built here; the README will say so until it is.

## Open for the author

- **Model download.** The agent needs a chat model that supports tool calling. Ollama has only
  `nomic-embed-text`. Proposed: one model of about 5 GB (Qwen 3 8B, or Llama 3.1 8B) from the
  Ollama library; exact name and size confirmed before the pull. The GPU had 12.5 of 16 GB in use
  at check time, so something else is holding video memory; the model still runs, but slower,
  until that frees up.

## Left to the builder

File layout, scenario details, prompt wording, the exact eval thresholds.
