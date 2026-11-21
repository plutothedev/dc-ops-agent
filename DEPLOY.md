<!-- (C) -->
# Deploying dc-ops-agent

**Not yet exercised.** The `Dockerfile` has not been built and none of the steps below have been run; there is no Docker on the author's machine. Treat this as a design that should work, not a tested procedure. The agent and its tests are tested; the container and collector wiring are not.

## Shape

The agent is a command line tool, not a service. It needs this package and an Ollama server that has the model. Run the container next to an Ollama host and point it there with `OLLAMA_BASE_URL`. The agent starts the MCP server as a child process inside the same container over stdio; nothing listens on a network port.

## Build and run

```
docker build -t dcops .
docker run --rm dcops scenarios
docker run --rm -e OLLAMA_BASE_URL=http://<ollama-host>:11434 dcops run --scenario chiller-low-flow --deny-writes
```

Pull the model on the Ollama host first: `ollama pull qwen3:8b`.

On the same machine as Ollama, the image default `http://host.docker.internal:11434` works on Docker Desktop. On Linux add `--add-host=host.docker.internal:host-gateway`, or use the host's address.

Without a TTY the default approver denies every write, so a containerised run never writes a work order unless you pass `--yes-to-writes`. `--draft-work-order` asks the agent to attempt one but does not change that. Mount a volume at `/app/out` if you do. The trace goes to `/app/traces` by default; mount that too to keep it.

The image uses an editable install because the data folder is found relative to the source tree. A plain (non-editable) install without `DCOPS_DATA` stops with `error: data folder not found at ...` and exit code 2. A job runner can read the exit code: 0 the run finished, 1 a guard stopped it (`step_cap` or `repeat_loop`), 2 the model call failed or a usage error, 130 interrupted. Exit code 0 does not mean the answer is right.

## Cloud VM or container service

- **VM with a GPU:** run Ollama on the VM, run the container on the same VM, and set `OLLAMA_BASE_URL` to the VM's address. Keep port 11434 closed to the internet; Ollama has no authentication.
- **Container service without a GPU:** run Ollama on a separate GPU host reachable over a private network and set `OLLAMA_BASE_URL` to it. Run the container as a one-off job per investigation.

## Environment variables

| Variable | Meaning | Default |
|---|---|---|
| `OLLAMA_BASE_URL` | Where the model (and optional embeddings) are served | `http://localhost:11434` (image: `http://host.docker.internal:11434`) |
| `DCOPS_DATA` | Folder with `scenarios/`, `runbooks/` and `site/`; overrides the bundled data | the repo's `data/` |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | OTLP/HTTP collector endpoint; spans are sent there when it is set and the `otlp` extra is installed | unset |

## Sending traces to an OTLP collector

Spans always go to a local JSONL file. To also send them to a collector, install the extra and set the endpoint:

```
pip install -e .[otlp]
OTEL_EXPORTER_OTLP_ENDPOINT=http://<collector>:4318 dcops run --scenario chiller-low-flow
```

In the container, install the extra in the image (change the `pip install` line in the `Dockerfile` to `pip install --no-cache-dir -e .[otlp]`) and pass the variable with `-e`. If the variable is set but the extra is missing, the run prints a note to stderr and carries on with the JSONL file only. The exporter is the OTLP/HTTP one, so use the collector's HTTP port (4318 by default). This path has not been tested against a real collector.
