# Starlight

**A/B(/C) evaluation harness for AI agents.**

Starlight runs two or three agent configurations against the same tasks in isolated containers, scores their execution traces with the [Snowflake Agent GPA framework](https://www.snowflake.com/en/blog/engineering/ai-agent-evaluation-gpa-framework/), and produces a side-by-side comparison report.

Use it to answer questions like:

- Does Opus do meaningfully better than Sonnet on my workload, and where exactly does it differ?
- Does adding the GitHub MCP server improve my agent's code-review quality?
- Did my new system prompt make things better or worse?
- Which skills are actually worth the cost?

---

## How it works

```
starlight run scenario.yaml
        │
        ├── Spins up an OTel Collector sidecar container
        ├── Runs each agent in its own isolated container (concurrently)
        ├── Stops the collector, parses traces and transcripts
        └── Scores each agent with the GPA framework (LLM-as-judge)
            and renders a side-by-side report
```

Each agent is scored across 7 GPA dimensions on a 0–3 scale:

| Dimension | What it measures |
|---|---|
| Goal Fulfillment | Did the agent achieve the stated goal? |
| Plan Quality | Did it decompose the goal into sensible subtasks? |
| Tool Selection | Did it pick the right tool for each step? |
| Plan Adherence | Did it follow the plan without skipping or reordering? |
| Tool Calling | Were tool invocations correct — right params, no hallucinations? |
| Logical Consistency | Is the reasoning internally consistent with what was observed? |
| Execution Efficiency | Did it take a minimal path, or waste steps? |

---

## Prerequisites

- **Python 3.11+**
- **Docker or Podman** — Docker or rootless Podman both work.
  - Podman on Fedora/RHEL: `systemctl --user start podman.socket` (Starlight starts it automatically if needed)
  - SELinux systems (Fedora, RHEL): Starlight calls `chcon` automatically — no manual steps required
- **Google Cloud project** with Vertex AI enabled and Claude models in [Model Garden](https://console.cloud.google.com/vertex-ai/model-garden)
  - Enable: `gcloud services enable aiplatform.googleapis.com`

---

## Installation

```bash
git clone https://github.com/your-org/starlight.git
cd starlight

# Install the CLI
pip install -e .

# Build the Claude Code agent container image
podman build -t starlight-claude-code:local docker/claude-code/
# or: docker build -t starlight-claude-code:local docker/claude-code/
```

Verify:

```bash
starlight --help
starlight run examples/01-model-comparison.yaml --dry-run
```

---

## Authentication

Starlight uses Vertex AI for both the GPA judge and the Claude Code agents.

```bash
# One-time: authenticate with Google Cloud
gcloud auth application-default login

# Set your GCP project (the one with Vertex AI enabled)
export GOOGLE_CLOUD_PROJECT="your-project-id"
```

The ADC credentials file (`~/.config/gcloud/application_default_credentials.json`) is automatically copied into agent containers with correct permissions — you don't need to do anything special.

> **Direct Anthropic API instead of Vertex AI?** Set `provider: anthropic` in `evaluation:` and export `ANTHROPIC_API_KEY`. In agent env blocks use `ANTHROPIC_API_KEY` instead of the Vertex vars.

---

## Quick start

```bash
export GOOGLE_CLOUD_PROJECT="your-project-id"

# See what would run without starting any containers
starlight run examples/04-grounded-summary.yaml --dry-run

# Run it for real
starlight run examples/04-grounded-summary.yaml
```

---

## Examples

Eight ready-to-run scenarios in `examples/`. Always start with `--dry-run` first.

| File | What it tests |
|---|---|
| `01-model-comparison.yaml` | Opus-4-8 vs Sonnet-4-6 on a summarization task |
| `02-skill-comparison.yaml` | With vs without GitHub MCP server on a research task |
| `03-regression-suite.yaml` | Multi-task regression suite with `--tag smoke` subset |
| `04-grounded-summary.yaml` | Structured "read then cite" prompt vs open-ended — hallucination benchmark |
| `05-local-skill.yaml` | With vs without Context7 skill (live SDK docs lookup) |
| `06-github-skill.yaml` | With vs without a skill cloned from a GitHub repo at evaluation time |
| `07-mcp-server.yaml` | With vs without a Jira MCP server on ticket-related tasks |
| `08-combined-skills.yaml` | Fully equipped agent (skill + GitHub skill + MCP) vs clean baseline |

```bash
# Single scenario
starlight run examples/01-model-comparison.yaml

# Multiple scenarios — only those run, results reported together
starlight run examples/01-model-comparison.yaml examples/03-regression-suite.yaml

# Filter to smoke-tagged tasks only
starlight run examples/03-regression-suite.yaml --tag smoke
```

---

## Writing your own scenario

### Full YAML reference

```yaml
version: "1"
name: My Evaluation

# ── Tasks ──────────────────────────────────────────────────────────────────────
# Every agent runs every task. 2 agents × 3 tasks = 6 container executions.
tasks:
  - id: task-id              # used with --task filter
    tags: [smoke, coding]    # used with --tag filter
    prompt: >
      The exact instruction you would give the agent.
      Name specific tools: "Use Bash to run...", "Use Read to open...".
      Vague prompts let agents skip tool use and answer from training data.
    ground_truth: >
      A description of what a correct, complete response looks like.
      The GPA judge compares the agent's output against this.
    timeout_minutes: 10      # default: 10

# ── Agents ─────────────────────────────────────────────────────────────────────
agents:                      # 1–3 per scenario
  - id: agent-a
    runtime: claude-code     # claude-code | langchain | custom

    # Claude Code only: which model to use
    model: claude-opus-4-8

    # Skills (Claude Code plugins) ─────────────────────────────────────────────
    # Skills run inside the Claude Code process and add slash commands/behaviors.
    # Each agent gets ONLY the skills listed here — no host ~/.claude is used.
    # Starlight generates a settings.json with enabledPlugins and mounts it.
    skills:
      # Local skill — found in ~/.claude/plugins/cache/<publisher>/<name>/
      # and mounted read-only into the container.
      - context7@claude-plugins-official

      # GitHub skill — cloned fresh from GitHub at evaluation time.
      # Reproducible: every run uses the current version of the repo.
      - id: deep-plan@piercelamb-plugins
        github: piercelamb/deep-implement

    # MCP servers ───────────────────────────────────────────────────────────────
    # MCP servers are separate subprocesses that Claude Code launches inside
    # the container. Declare the full launch spec here — no host files are used.
    # Installed automatically at startup from 'npx -y <package>' args.
    mcp_servers:
      github:
        command: npx
        args: ["-y", "@modelcontextprotocol/server-github"]
        env:
          GITHUB_TOKEN: ${GITHUB_TOKEN}   # ${VAR} interpolated from shell

    # Volume mounts ─────────────────────────────────────────────────────────────
    # Mount host paths into the container. ${VAR} interpolation is supported.
    # Files with restrictive permissions (e.g. ADC credentials at mode 600)
    # are automatically copied and chmod 644'd before mounting — no manual steps.
    volumes:
      ${PWD}: /repo                                                  # your codebase
      ${HOME}/.config/gcloud/application_default_credentials.json: /tmp/adc.json

    # Environment variables passed to the agent container
    env:
      ANTHROPIC_VERTEX_PROJECT_ID: ${GOOGLE_CLOUD_PROJECT}
      CLOUD_ML_REGION: us-east5
      CLAUDE_CODE_USE_VERTEX: "1"
      GOOGLE_APPLICATION_CREDENTIALS: /tmp/adc.json

  - id: agent-b
    runtime: claude-code
    model: claude-sonnet-4-6
    # No skills, no MCP servers — clean baseline for A/B comparison.
    volumes:
      ${PWD}: /repo
      ${HOME}/.config/gcloud/application_default_credentials.json: /tmp/adc.json
    env:
      ANTHROPIC_VERTEX_PROJECT_ID: ${GOOGLE_CLOUD_PROJECT}
      CLOUD_ML_REGION: us-east5
      CLAUDE_CODE_USE_VERTEX: "1"
      GOOGLE_APPLICATION_CREDENTIALS: /tmp/adc.json

# ── Evaluation ─────────────────────────────────────────────────────────────────
evaluation:
  provider: vertex            # vertex | anthropic
  judge_model: claude-sonnet-4-6
  vertex_project: ${GOOGLE_CLOUD_PROJECT}
  vertex_region: us-east5
  metrics: all                # or a list: [goal_fulfillment, tool_selection]
  pass_threshold: 2.0         # exit code 1 if any agent scores below this

# ── Container ──────────────────────────────────────────────────────────────────
container:
  runtime: auto               # docker | podman | auto (tries docker first)

# ── Output ─────────────────────────────────────────────────────────────────────
output:
  format: auto                # auto (detects CI) | table | json | junit
  file: results.json          # always written; path relative to cwd
```

### Non-Claude Code agents

For LangChain or custom agents, point to a container image:

```yaml
agents:
  - id: langchain-agent
    runtime: langchain
    image: my-registry/my-agent:latest
    env:
      OPENAI_API_KEY: ${OPENAI_API_KEY}
      # OTEL_EXPORTER_OTLP_ENDPOINT is injected automatically

  - id: custom-agent
    runtime: custom
    image: my-registry/custom:latest
    command: "python agent.py"
    env:
      OTEL_EXPORTER_OTLP_ENDPOINT: "http://starlight-collector:4318"
```

---

## Agent extensions: skills and MCP servers

Claude Code has two separate extension systems. Starlight handles both.

### Skills (Claude Code plugins)

Skills are JavaScript packages that run **inside** the Claude Code process. They add slash commands and behaviors (e.g. `context7@claude-plugins-official` adds live documentation lookup, `superpowers@claude-plugins-official` adds AI workflows).

```yaml
skills:
  # Local skill — Starlight finds it in ~/.claude/plugins/cache/<publisher>/<name>/
  # and mounts it read-only into the container.
  # Install locally first: claude skill install context7@claude-plugins-official
  - context7@claude-plugins-official

  # GitHub skill — Starlight git-clones the repo at evaluation time.
  # No local install needed. Version is detected from the repo's package.json.
  - id: my-tool@my-org
    github: my-org/my-claude-skill-repo
```

Starlight writes an `enabledPlugins` block to a generated `settings.json` and mounts it at `/home/agent/.claude/settings.json`. **No host `~/.claude` files are ever used** — each agent gets exactly the skills listed in the YAML.

> **Adding a skill to the image (optional):** If a skill has native binaries, you may also need to add it to `docker/claude-code/Dockerfile`. Most skills are pure JavaScript and don't require this.

### MCP servers

MCP servers are **separate processes** that Claude Code launches as subprocesses inside the container. They expose tools via the MCP protocol (GitHub API, databases, Jira, etc.).

```yaml
mcp_servers:
  github:
    command: npx
    args: ["-y", "@modelcontextprotocol/server-github"]
    env:
      GITHUB_TOKEN: ${GITHUB_TOKEN}

  jira:
    command: npx
    args: ["-y", "@modelcontextprotocol/server-atlassian"]
    env:
      JIRA_URL: ${JIRA_URL}
      JIRA_API_TOKEN: ${JIRA_API_TOKEN}
```

Starlight writes a `mcpServers` block to the generated `settings.json`. The server package is **installed automatically at container startup** — no Dockerfile changes or image rebuild required.

For `command: npx`, Starlight detects the npm package from the first non-flag argument in `args` and passes it to the container as `STARLIGHT_MCP_PACKAGES`. The entrypoint runs `npm install -g <package>` before starting Claude Code (~2 seconds per package).

To skip the per-run install (offline use, or for speed after the first run), add `install: ""` to tell Starlight the binary is already in the image:

```yaml
mcp_servers:
  github:
    command: npx
    args: ["-y", "@modelcontextprotocol/server-github"]
    install: ""   # binary pre-installed in image; skip runtime install
```

To pre-install in the image, add to `docker/claude-code/Dockerfile` and rebuild:
```dockerfile
RUN npm install -g @modelcontextprotocol/server-github
```

### What gets generated

For an agent with both a skill and an MCP server, Starlight writes:

```json
{
  "enabledPlugins": {
    "context7@claude-plugins-official": true
  },
  "mcpServers": {
    "github": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": { "GITHUB_TOKEN": "ghp_..." }
    }
  }
}
```

An agent with no `skills:` and no `mcp_servers:` gets no `settings.json` at all — a completely clean Claude Code instance.

---

## Writing effective prompts

**The most common failure mode:** agents answer from training-data knowledge instead of actually reading files or calling tools. The GPA judge catches this as a Logical Consistency failure (1/3).

**What doesn't work:**
```yaml
prompt: >
  Read the README and top-level source files, then write a summary.
```
The agent "reads" with its training memory and produces a plausible-sounding but fabricated answer.

**What works:**
```yaml
prompt: >
  Do these steps in order:
  Step 1 — Bash: run `ls /repo`
  Step 2 — Bash: run `cat /repo/README.md`
  Step 3 — Read: open /repo/starlight/orchestrator.py
  Step 4 — Read: open /repo/starlight/evaluator.py

  After completing all four steps, write your summary.
  For each claim, note which step it came from.
  Do not include anything not found in Steps 1-4.
```

The mandatory step sequence + citation requirement forces actual tool use and makes hallucination detectable. The citation instruction drops Logical Consistency failures from 1/3 to 3/3 in practice (see `examples/04-grounded-summary.yaml`).

---

## CLI reference

```
starlight run [OPTIONS] SCENARIOS...
```

| Option | Description |
|---|---|
| `SCENARIOS` | One or more YAML files. Only those scenarios are run. |
| `--task TEXT` | Run only tasks with this ID (repeatable). |
| `--tag TEXT` | Run only tasks with this tag (repeatable). |
| `--dry-run` | Print execution plan; start no containers. |
| `--output FORMAT` | `auto` (default), `table`, `json`, or `junit`. |
| `--verbose` | Show full judge reasoning for every metric, including 3/3 ones. |
| `--trace` | Show step-by-step tool call log per agent. |

**Exit codes:** `0` if all agents score ≥ `pass_threshold`; `1` otherwise.

---

## Understanding the report

```
Model Comparison  ·  Task: summarize-repo
────────────────────────────────────────────────────────────────────────────────
  Metric                 opus (opus-4-8)         sonnet (sonnet-4-6)
  ──────────────────     ──────────────────      ────────────────────
  Goal Fulfillment         3 / 3   ████████        2 / 3   █████░░░
  Plan Quality             3 / 3   ████████        2 / 3   █████░░░
  Tool Selection           3 / 3   ████████        3 / 3   ████████
  Plan Adherence           3 / 3   ████████        3 / 3   ████████
  Tool Calling             2 / 3   █████░░░        2 / 3   █████░░░
  Logical Consistency      3 / 3   ████████        2 / 3   █████░░░
  Execution Efficiency     2 / 3   █████░░░        2 / 3   █████░░░
  ──────────────────     ──────────────────      ────────────────────
  GPA Score                2.86 / 3   ✓            2.29 / 3   ✓

  ▸ sonnet (claude-sonnet-4-6)
  Read README.md and pyproject.toml, then produced a summary.

    Goal Fulfillment (2/3)
    Summary omits the "get started" section required by the ground truth.

    Logical Consistency (2/3)
    Claims the evaluator is a "TruLens integration" but the code uses
    direct Anthropic API calls — a contradiction with what was actually read.
```

- **Score table** — quick scan; color-coded green/yellow/red
- **Detail blocks** — only appear for metrics scoring below 3/3; explain exactly why
- **"All metrics 3/3"** — hint to use `--verbose` to see the judge's reasoning even for perfect scores
- **Summary** — cross-task GPA averages and each agent's weakest metric

---

## Results JSON

`results.json` is always written regardless of output format:

```json
{
  "scenario_name": "Model Comparison — Opus vs Sonnet",
  "task_results": [
    {
      "task_id": "summarize-repo",
      "task_prompt": "...",
      "ground_truth": "...",
      "gpa_scores": {
        "opus": {
          "goal_fulfillment": 3,
          "plan_quality": 3,
          "tool_selection": 3,
          "plan_adherence": 3,
          "tool_calling": 2,
          "logical_consistency": 3,
          "execution_efficiency": 2,
          "gpa": 2.857,
          "rationales": { "tool_calling": "One redundant file read." },
          "reasoning": { "tool_calling": "The agent called list_files after already having..." }
        }
      }
    }
  ]
}
```

---

## CI integration

```yaml
# .github/workflows/agent-eval.yml
- name: Authenticate to Google Cloud
  uses: google-github-actions/auth@v2
  with:
    workload_identity_provider: ${{ secrets.WIF_PROVIDER }}
    service_account: ${{ secrets.WIF_SERVICE_ACCOUNT }}

- name: Build agent image
  run: docker build -t starlight-claude-code:local docker/claude-code/

- name: Run regression suite
  env:
    GOOGLE_CLOUD_PROJECT: ${{ vars.GOOGLE_CLOUD_PROJECT }}
  run: |
    pip install -e .
    starlight run examples/03-regression-suite.yaml --tag smoke --output json
```

`--output json` writes to stdout so CI can parse it. Exit code `1` fails the build if any agent scores below `pass_threshold`.

---

## Troubleshooting

**"Neither Docker nor Podman is available"**
Podman is installed but the REST API socket isn't running. Starlight tries to start it automatically. If that fails:
```bash
systemctl --user start podman.socket
systemctl --user enable podman.socket   # to start it on login
```

**"Permission denied" writing to /workspace inside container**
SELinux is blocking the container from writing to the mounted temp directory. Starlight calls `chcon container_file_t` automatically — this should not require manual action. If it still fails, verify `chcon` is available:
```bash
which chcon
```

**Scores showing N/A**
The GPA judge's JSON response couldn't be parsed. This usually means the judge response was too long (unlikely with max_tokens=1024) or wrapped in unexpected markdown. Check `results.json` for the raw rationale — it will say `"parse error"` for affected metrics.

**Agent not using tools (all scores 0/3 for plan quality)**
Claude Code in print mode (`-p`) answers from training data unless the prompt explicitly names which tools to call. See [Writing effective prompts](#writing-effective-prompts).

**ADC file permission denied in container**
If you see `EACCES: permission denied, open '/tmp/adc.json'`, the credentials file was not auto-copied with relaxed permissions. Check that the file exists at `~/.config/gcloud/application_default_credentials.json` on your host:
```bash
ls -la ~/.config/gcloud/application_default_credentials.json
```

---

## Project layout

```
starlight/
├── docker/
│   └── claude-code/
│       ├── Dockerfile        # Claude Code agent image
│       └── entrypoint.sh     # Runs claude -p, exports transcript
├── examples/                 # Ready-to-run scenario files (01–08)
├── results/                  # Output directory for results.json files
├── starlight/
│   ├── cli.py                # Click entry point
│   ├── config.py             # Pydantic v2 YAML schema (ScenarioConfig, SkillSpec, etc.)
│   ├── models.py             # Shared dataclasses (AgentRun, GpaScore, GpaReport)
│   ├── container.py          # Docker + Podman SDK abstraction
│   ├── collector.py          # OTel Collector sidecar lifecycle
│   ├── orchestrator.py       # Full evaluation lifecycle
│   ├── traces.py             # OTLP JSON/NDJSON trace parser
│   ├── evaluator.py          # GPA evaluation via Anthropic API (LLM-as-judge)
│   ├── report.py             # Terminal (rich) + JSON rendering
│   └── runtime/
│       ├── base.py           # AgentAdapter ABC
│       ├── claude_code.py    # Claude Code adapter (transcript → tool calls)
│       ├── langchain.py      # LangChain adapter (OTLP env injection)
│       └── custom.py         # Custom/BYO adapter
└── tests/
    ├── unit/                 # 38 unit tests — no containers needed
    └── integration/          # Full pipeline test — requires Docker/Podman
```

---

## GPA framework

Starlight implements the [Snowflake Agent GPA framework](https://arxiv.org/html/2510.08847v2) directly using the Anthropic API. Each of the 7 metrics is scored by an LLM judge that examines the agent's full execution trace and compares it against the `ground_truth`. Scores are 0–3 with defined anchors at the extremes.

The judge model is configurable per scenario (`evaluation.judge_model`). The default is `claude-sonnet-4-6`. The judge strips markdown code fences from its responses automatically, so switching to a model that formats differently will not cause parse errors.
