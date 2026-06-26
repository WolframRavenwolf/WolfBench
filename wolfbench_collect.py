#!/usr/bin/env python3
"""Collect Harbor eval results from all exe.dev VMs.

Scans all harbor-evals VMs via SSH, reads result.json + config.json
from each run, and outputs structured JSON + summary table.

Runs are split into two files:
  - wolfbench_results.json          Valid runs (89 tasks, full Terminal-Bench 2.0)
  - wolfbench_results_excluded.json Excluded runs (partials, tests, aborted, infra failures)

Each excluded run includes an "exclude_reason" field explaining why.

Usage:
    python wolfbench_collect.py                    # Discover VMs, scan, output JSON
    python wolfbench_collect.py --table             # Print summary table
    python wolfbench_collect.py --leaderboard       # Print aggregated leaderboard
    python wolfbench_collect.py --vms host1 host2   # Scan specific VMs

Requirements:
    - SSH access to exe.dev VMs (keys configured)
    - No Python dependencies (stdlib only)
"""

import argparse
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path


COST_PER_MILLION_SCALE = 1_000_000


# W&B Inference prices, USD per 1M tokens, checked against the public
# pricing page (https://wandb.ai/site/inference/) on 2026-06-24.
WANDB_INFERENCE_PRICING_PER_1M = {
    "glm-5.2": {"input": 1.39, "output": 4.40, "cache_read": 0.26},
    "deepseek-v4-pro": {"input": 1.74, "output": 3.46, "cache_read": 0.14},
    "deepseek-v4-flash": {"input": 0.14, "output": 0.28, "cache_read": 0.07},
    "kimi-k2.6": {"input": 0.95, "output": 4.00, "cache_read": 0.16},
    "kimi-k2.5": {"input": 0.60, "output": 3.00, "cache_read": 0.10},
    "glm-5.1": {"input": 1.40, "output": 4.40, "cache_read": 0.26},
    "glm-5": {"input": 1.00, "output": 3.20, "cache_read": None},
    "minimax-m2.5": {"input": 0.30, "output": 1.20, "cache_read": None},
    "gemma-4-31b": {"input": 0.30, "output": 1.25, "cache_read": None},
    "nemotron-3-ultra": {"input": 0.75, "output": 2.75, "cache_read": 0.15},
    "nemotron-3-super-120b": {"input": 0.20, "output": 0.80, "cache_read": None},
}


WANDB_PRICING_ALIASES = {
    "DeepSeek-V4-Pro [W&B]": "deepseek-v4-pro",
    "wandb/deepseek-ai/DeepSeek-V4-Pro": "deepseek-v4-pro",
    "DeepSeek-V4-Flash [W&B]": "deepseek-v4-flash",
    "wandb/deepseek-ai/DeepSeek-V4-Flash": "deepseek-v4-flash",
    "Kimi K2.6 [W&B]": "kimi-k2.6",
    "wandb/moonshotai/Kimi-K2.6": "kimi-k2.6",
    "Kimi K2.5 (int4) [W&B]": "kimi-k2.5",
    "Kimi K2.5 (nvfp4) [W&B]": "kimi-k2.5",
    "wandb/moonshotai/Kimi-K2.5": "kimi-k2.5",
    "GLM-5.2 [W&B]": "glm-5.2",
    "wandb/zai-org/GLM-5.2": "glm-5.2",
    "GLM-5.1 [W&B]": "glm-5.1",
    "wandb/zai-org/GLM-5.1": "glm-5.1",
    "GLM-5-FP8 [W&B]": "glm-5",
    "wandb/zai-org/GLM-5-FP8": "glm-5",
    "MiniMax M2.5 [W&B]": "minimax-m2.5",
    "wandb/MiniMaxAI/MiniMax-M2.5": "minimax-m2.5",
    "Gemma 4 31B [W&B]": "gemma-4-31b",
    "wandb/google/gemma-4-31B-it": "gemma-4-31b",
    "NVIDIA-Nemotron-3-Ultra-550B-A55B [W&B]": "nemotron-3-ultra",
    "wandb/nvidia/NVIDIA-Nemotron-3-Ultra-550B-A55B": "nemotron-3-ultra",
    "NVIDIA-Nemotron-3-Super-120B-A12B-FP8 [W&B]": "nemotron-3-super-120b",
    "wandb/nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-FP8": "nemotron-3-super-120b",
}
WANDB_PRICING_ALIASES = {
    alias.lower(): pricing_key
    for alias, pricing_key in WANDB_PRICING_ALIASES.items()
}


# Fallback list prices, USD per 1M tokens, for agents that record tokens but do
# not emit per-task costs. These keep historical WolfBench snapshots complete
# without rerunning benchmarks.
TOKEN_PRICING_PER_1M = {
    "anthropic-claude-opus-4-6": {
        "input": 5.00,
        "cache_read": 0.50,
        "cache_creation": 6.25,
        "output": 25.00,
    },
    "anthropic-claude-opus-4-7": {
        "input": 5.00,
        "cache_read": 0.50,
        "cache_creation": 6.25,
        "output": 25.00,
    },
    "anthropic-claude-sonnet-4-6": {
        "input": 3.00,
        "cache_read": 0.30,
        "cache_creation": 3.75,
        "output": 15.00,
    },
    "google-gemini-3-5-flash": {
        "input": 1.50,
        "cache_read": 0.15,
        "output": 9.00,
    },
    "openai-gpt-5-3-codex": {
        "input": 1.75,
        "cache_read": 0.175,
        "output": 14.00,
    },
    "openai-gpt-5-4": {
        "input": 2.50,
        "cache_read": 0.25,
        "output": 15.00,
    },
    "openai-gpt-5-4-mini": {
        "input": 0.75,
        "cache_read": 0.075,
        "output": 4.50,
    },
    "openai-gpt-5-4-nano": {
        "input": 0.20,
        "cache_read": 0.02,
        "output": 1.25,
    },
    "openai-gpt-5-5": {
        "input": 5.00,
        "cache_read": 0.50,
        "output": 30.00,
    },
    "openrouter-glm-5-turbo": {
        "input": 1.20,
        "cache_read": 0.24,
        "output": 4.00,
    },
    "openrouter-kimi-k2-6": {
        "input": 0.95,
        "cache_read": 0.16,
        "output": 4.00,
    },
    "openrouter-minimax-m2-7": {
        "input": 0.30,
        "cache_read": 0.06,
        "output": 1.20,
    },
    "mistral-small-2603": {
        "input": 0.15,
        "cache_read": 0.015,
        "output": 0.60,
    },
}


TOKEN_PRICING_ALIASES = {
    "anthropic/claude-opus-4-6": "anthropic-claude-opus-4-6",
    "claude opus 4.6": "anthropic-claude-opus-4-6",
    "cursor/claude-4.6-opus-high-thinking": "anthropic-claude-opus-4-6",
    "anthropic/claude-opus-4-7": "anthropic-claude-opus-4-7",
    "claude opus 4.7": "anthropic-claude-opus-4-7",
    "anthropic/claude-sonnet-4-6": "anthropic-claude-sonnet-4-6",
    "claude sonnet 4.6": "anthropic-claude-sonnet-4-6",
    "google/gemini-3.5-flash": "google-gemini-3-5-flash",
    "gemini 3.5 flash": "google-gemini-3-5-flash",
    "openai/gpt-5.3-codex": "openai-gpt-5-3-codex",
    "gpt-5.3-codex": "openai-gpt-5-3-codex",
    "openai/gpt-5.4": "openai-gpt-5-4",
    "gpt-5.4": "openai-gpt-5-4",
    "openai/gpt-5.4-mini": "openai-gpt-5-4-mini",
    "gpt‑5.4 mini": "openai-gpt-5-4-mini",
    "gpt-5.4 mini": "openai-gpt-5-4-mini",
    "openai/gpt-5.4-nano": "openai-gpt-5-4-nano",
    "gpt‑5.4 nano": "openai-gpt-5-4-nano",
    "gpt-5.4 nano": "openai-gpt-5-4-nano",
    "openai/gpt-5.5": "openai-gpt-5-5",
    "cursor/gpt-5.5-high": "openai-gpt-5-5",
    "gpt-5.5": "openai-gpt-5-5",
    "openrouter/z-ai/glm-5-turbo": "openrouter-glm-5-turbo",
    "glm-5-turbo": "openrouter-glm-5-turbo",
    "openrouter/moonshotai/kimi-k2.6": "openrouter-kimi-k2-6",
    "kimi k2.6 [moonshot ai]": "openrouter-kimi-k2-6",
    "openrouter/minimax/minimax-m2.7": "openrouter-minimax-m2-7",
    "minimax m2.7": "openrouter-minimax-m2-7",
    "mistral/mistral-small-2603": "mistral-small-2603",
    "mistral small 4 119b a6b": "mistral-small-2603",
}


SSH_OPTS = [
    "-o", "ConnectTimeout=10",
    "-o", "BatchMode=yes",
    "-o", "StrictHostKeyChecking=accept-new",
]


def ssh_run(vm: str, command: str, timeout: int = 60) -> tuple[str, str, int]:
    """Run a command on a VM via SSH. Returns (stdout, stderr, returncode)."""
    proc = subprocess.run(
        ["ssh", *SSH_OPTS, vm, command],
        capture_output=True, text=True, timeout=timeout,
    )
    return proc.stdout, proc.stderr, proc.returncode


def discover_vms() -> list[str]:
    """Discover all VMs from exe.dev."""
    print("Discovering VMs from exe.dev...", file=sys.stderr)
    proc = subprocess.run(
        ["ssh", *SSH_OPTS, "exe.dev", "ls"],
        capture_output=True, text=True, timeout=60,
    )
    if proc.returncode != 0:
        print(f"Error listing VMs: {proc.stderr}", file=sys.stderr)
        return []

    vms = []
    for line in proc.stdout.splitlines():
        # Parse "  • harbor-evals-oc.exe.xyz - running (boldsoftware/exeuntu)"
        line = line.strip()
        if line.startswith("•"):
            parts = line.split()
            if len(parts) >= 2:
                hostname = parts[1]
                if hostname.endswith(".exe.xyz"):
                    vms.append(hostname)
    print(f"Found {len(vms)} exe.dev VMs", file=sys.stderr)
    return vms


def discover_hetzner_vms() -> list[dict]:
    """Discover VMs from Hetzner Cloud via hcloud CLI.

    Returns list of dicts: [{"name": "harbor-evals", "ip": "46.x.x.x", "status": "running"}]
    Requires `hcloud` CLI to be installed and authenticated.
    """
    print("Discovering VMs from Hetzner Cloud...", file=sys.stderr)
    try:
        proc = subprocess.run(
            ["hcloud", "server", "list", "-o", "json"],
            capture_output=True, text=True, timeout=60,
        )
    except FileNotFoundError:
        print("Error: hcloud CLI not found", file=sys.stderr)
        return []
    if proc.returncode != 0:
        print(f"Error listing Hetzner servers: {proc.stderr}", file=sys.stderr)
        return []
    try:
        servers = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        print(f"Error parsing Hetzner response: {e}", file=sys.stderr)
        return []
    vms = []
    for s in servers:
        ipv4 = s.get("public_net", {}).get("ipv4", {}).get("ip")
        if ipv4:
            vms.append({"name": s["name"], "ip": ipv4, "status": s.get("status", "?")})
    print(f"Found {len(vms)} Hetzner servers", file=sys.stderr)
    return vms


def find_runs_on_vm(vm: str) -> list[str]:
    """Find all run directories (with result.json + config.json) on a VM."""
    command = r"""
for base in ~/harbor-evals ~/harbor ~/harbor-5; do
  [ -d "$base" ] || continue
  jobs_dir="$base/jobs"
  [ -d "$jobs_dir" ] || continue
  find "$jobs_dir" -mindepth 3 -maxdepth 3 -type f -name result.json \
    2>/dev/null | sort | while read -r result; do
    dir="${result%/result.json}"
    [ -f "$dir/result.json" ] && [ -f "$dir/config.json" ] && echo "$dir"
  done
done
"""
    stdout, stderr, rc = ssh_run(vm, command, timeout=30)
    if rc != 0:
        print(f"  [{vm}] Error finding runs: {stderr.strip()}", file=sys.stderr)
        return []
    return [line.strip() for line in stdout.splitlines() if line.strip()]


def read_run_data(vm: str, run_dir: str) -> dict | None:
    """Read result.json, config.json, and aggregate per-task token counts."""
    # Read result + config, then sum per-task token metrics in one SSH call
    # Token aggregation script — must use ONLY double quotes inside Python code
    # because it's wrapped in single quotes for the shell
    token_script = (
        'import json,glob,sys,os;tin=tout=tcache=0;cost=0.0;ver=None\n'
        'flist=glob.glob(sys.argv[1]+"/*/result.json")\n'
        'for f in flist:\n'
        ' try:\n'
        '  d=json.load(open(f))\n'
        '  ar=d.get("agent_result") or {}\n'
        '  tin+=ar.get("n_input_tokens",0) or 0\n'
        '  tout+=ar.get("n_output_tokens",0) or 0\n'
        '  tcache+=ar.get("n_cache_tokens",0) or 0\n'
        '  cost+=ar.get("cost_usd",0) or 0\n'
        '  if ver is None:\n'
        '   ai=d.get("agent_info") or {}\n'
        '   v=ai.get("version","")\n'
        '   if v and v!="unknown": ver=v\n'
        '   elif ver is None:\n'
        '    cc=os.path.join(os.path.dirname(f),"agent","claude-code.txt")\n'
        '    if os.path.exists(cc):\n'
        '     try:\n'
        '      l=open(cc).readline()\n'
        '      ver=json.loads(l).get("claude_code_version") or None\n'
        '     except:pass\n'
        ' except:pass\n'
        'print(json.dumps({"in":tin,"out":tout,"cache":tcache,"cost":round(cost,2),"ver":ver}))'
    )
    command = (
        f'cat "{run_dir}/result.json" && echo "---JSON_SEPARATOR---" && '
        f'cat "{run_dir}/config.json" && echo "---JSON_SEPARATOR---" && '
        f"python3 -c '{token_script}' \"{run_dir}\""
    )
    stdout, stderr, rc = ssh_run(vm, command, timeout=30)
    if rc != 0:
        print(f"  [{vm}] Error reading {run_dir}: {stderr.strip()}", file=sys.stderr)
        return None

    parts = stdout.split("---JSON_SEPARATOR---")
    if len(parts) < 2:
        print(f"  [{vm}] Unexpected output format for {run_dir}", file=sys.stderr)
        return None

    try:
        result = json.loads(parts[0].strip())
        config = json.loads(parts[1].strip())
    except json.JSONDecodeError as e:
        print(f"  [{vm}] JSON parse error in {run_dir}: {e}", file=sys.stderr)
        return None

    # Token aggregation (optional — may fail on older runs without per-task results)
    tokens = None
    if len(parts) >= 3:
        try:
            tokens = json.loads(parts[2].strip())
        except (json.JSONDecodeError, IndexError):
            pass

    return {"result": result, "config": config, "tokens": tokens}


def _model_info_has_per_million_costs(config: dict) -> bool:
    """Detect configs where per-million prices were stored in per-token fields."""
    agent_cfg = config.get("agents", [{}])[0]
    model_info = (agent_cfg.get("kwargs") or {}).get("model_info") or {}
    cost_keys = (
        "input_cost_per_token",
        "output_cost_per_token",
        "cache_creation_input_token_cost",
        "cache_read_input_token_cost",
    )
    for key in cost_keys:
        try:
            value = float(model_info.get(key) or 0)
        except (TypeError, ValueError):
            continue
        if value >= 0.001:
            return True
    return False


def _normalize_cost_usd(cost, config: dict):
    try:
        value = float(cost)
    except (TypeError, ValueError):
        return cost
    if value > 10_000 and _model_info_has_per_million_costs(config):
        return round(value / COST_PER_MILLION_SCALE, 2)
    return cost


def _positive_cost_usd(cost) -> bool:
    try:
        return float(cost) > 0
    except (TypeError, ValueError):
        return False


def _rate_per_1m(cost) -> float | None:
    try:
        value = float(cost)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    if value < 0.001:
        return value * COST_PER_MILLION_SCALE
    return value


def _pricing_from_model_info(config: dict) -> dict | None:
    agent_cfg = config.get("agents", [{}])[0]
    model_info = (agent_cfg.get("kwargs") or {}).get("model_info") or {}
    input_rate = _rate_per_1m(model_info.get("input_cost_per_token"))
    output_rate = _rate_per_1m(model_info.get("output_cost_per_token"))
    if input_rate is None or output_rate is None:
        return None

    pricing = {"input": input_rate, "output": output_rate}
    cache_read = _rate_per_1m(model_info.get("cache_read_input_token_cost"))
    cache_creation = _rate_per_1m(
        model_info.get("cache_creation_input_token_cost")
    )
    if cache_read is not None:
        pricing["cache_read"] = cache_read
    if cache_creation is not None:
        pricing["cache_creation"] = cache_creation
    return pricing


def _fallback_pricing_for_model(model_name: str, model_display: str) -> dict | None:
    candidates = []
    for value in (model_name, model_display):
        if value:
            candidates.append(str(value).strip().lower())

    for candidate in candidates:
        pricing_key = TOKEN_PRICING_ALIASES.get(candidate)
        if pricing_key:
            return TOKEN_PRICING_PER_1M[pricing_key]
    return None


def _split_uncached_and_cached_input(input_tokens, cache_tokens) -> tuple[float, float]:
    input_tokens = input_tokens or 0
    cache_tokens = cache_tokens or 0
    if cache_tokens and input_tokens >= cache_tokens:
        return input_tokens - cache_tokens, cache_tokens
    return input_tokens, cache_tokens


def _calculate_token_cost_usd(tokens: dict | None, pricing: dict | None):
    if not tokens or not pricing:
        return None

    input_tokens = tokens.get("in") or 0
    cache_tokens = tokens.get("cache") or 0
    cache_write_tokens = tokens.get("cache_write") or 0
    output_tokens = tokens.get("out") or 0
    if not input_tokens and not cache_tokens and not cache_write_tokens and not output_tokens:
        return None

    input_rate = pricing["input"]
    cache_rate = pricing.get("cache_read")
    if cache_rate is None:
        cache_rate = input_rate
    cache_creation_rate = pricing.get("cache_creation")
    if cache_creation_rate is None:
        cache_creation_rate = input_rate

    if cache_write_tokens:
        uncached_input_tokens = input_tokens
        cached_input_tokens = cache_tokens
        cache_creation_tokens = cache_write_tokens
        uncached_input_rate = input_rate
    else:
        uncached_input_tokens, cached_input_tokens = _split_uncached_and_cached_input(
            input_tokens, cache_tokens
        )
        cache_creation_tokens = 0
        uncached_input_rate = (
            cache_creation_rate
            if cached_input_tokens and pricing.get("cache_creation") is not None
            else input_rate
        )

    cost = (
        uncached_input_tokens * uncached_input_rate
        + cache_creation_tokens * cache_creation_rate
        + cached_input_tokens * cache_rate
        + output_tokens * pricing["output"]
    ) / COST_PER_MILLION_SCALE
    return round(cost, 2)


def _calculate_fallback_cost_usd(tokens: dict | None, config: dict,
                                 model_name: str, model_display: str):
    pricing = (
        _pricing_from_model_info(config)
        or _fallback_pricing_for_model(model_name, model_display)
    )
    return _calculate_token_cost_usd(tokens, pricing)


def _wandb_pricing_for_model(model_name: str, model_display: str) -> dict | None:
    model_name = str(model_name or "").strip()
    model_display = str(model_display or "").strip()
    if not model_name.lower().startswith("wandb/") and "[W&B]" not in model_display:
        return None

    candidates = []
    for value in (model_name, model_display):
        if not value:
            continue
        text = str(value).strip()
        candidates.append(text)
        if "wandb/" in text:
            candidates.append("wandb/" + text.split("wandb/", 1)[1])

    for candidate in candidates:
        pricing_key = WANDB_PRICING_ALIASES.get(candidate.lower())
        if pricing_key:
            return WANDB_INFERENCE_PRICING_PER_1M[pricing_key]
    return None


def _calculate_wandb_cost_usd(tokens: dict | None, model_name: str,
                              model_display: str):
    pricing = _wandb_pricing_for_model(model_name, model_display)
    return _calculate_token_cost_usd(tokens, pricing)


def extract_metrics(vm: str, run_dir: str, result: dict, config: dict,
                    tokens: dict | None = None) -> dict:
    """Extract key metrics from result.json and config.json into a flat record."""
    # Parse run path for context
    # e.g., /home/exedev/harbor/jobs/oc-claude-sonnet-4-6/2026-03-01__13-43-12
    # or    /home/exedev/harbor-evals/jobs-kimi-k2.5-nt5/2026-02-15__02-15-16
    parts = run_dir.split("/")
    timestamp = parts[-1]  # 2026-03-01__13-43-12

    # Agent info from config
    agent_cfg = config.get("agents", [{}])[0]
    agent_name = agent_cfg.get("name", "unknown")
    model_name = agent_cfg.get("model_name", "unknown")
    agent_timeout = agent_cfg.get("override_timeout_sec")
    agent_kwargs = agent_cfg.get("kwargs", {})

    # User-defined display overrides (empty = use auto-derived values)
    model_display = config.get("model_display", "")
    thinking_display = config.get("thinking_display", "")
    version_display = config.get("version_display", "")
    provider_display = config.get("provider_display", "")
    vendor_display = config.get("vendor_display", "")

    # Orchestrator config
    orch = config.get("orchestrator", {})
    concurrency = orch.get("n_concurrent_trials", None)

    # Environment config
    env = config.get("environment", {})
    env_type = env.get("type", "unknown")
    cpus = env.get("override_cpus")
    memory_mb = env.get("override_memory_mb")

    # Result metrics
    stats = result.get("stats", {})
    n_trials = stats.get("n_trials", 0)
    n_errors = stats.get("n_errors", 0)

    # Score from evals — take first eval's first metric mean
    evals = stats.get("evals", {})
    eval_name = next(iter(evals), "")
    eval_data = evals.get(eval_name, {})
    metrics = eval_data.get("metrics", [{}])
    score = metrics[0].get("mean", None) if metrics else None

    # Task counts from reward_stats
    reward_stats = eval_data.get("reward_stats", {}).get("reward", {})
    n_passed = len(reward_stats.get("1.0", []))
    n_failed = len(reward_stats.get("0.0", []))

    # Passed and failed task names (without hash suffix)
    passed_tasks = sorted(t.split("__")[0] for t in reward_stats.get("1.0", []))
    failed_tasks = sorted(t.split("__")[0] for t in reward_stats.get("0.0", []))

    # Error breakdown
    exception_stats = eval_data.get("exception_stats", {})
    error_breakdown = {k: len(v) for k, v in exception_stats.items()}

    # Timing
    started_at = result.get("started_at")
    finished_at = result.get("finished_at")
    duration_sec = None
    if started_at and finished_at:
        try:
            t0 = datetime.fromisoformat(started_at)
            t1 = datetime.fromisoformat(finished_at)
            duration_sec = (t1 - t0).total_seconds()
        except (ValueError, TypeError):
            pass

    # Agent-specific config details
    temperature = agent_kwargs.get("temperature")
    thinking = None
    # terminus-2 / vLLM path
    extra_body = agent_kwargs.get("llm_kwargs", {}).get("extra_body", {})
    if "chat_template_kwargs" in extra_body:
        thinking = extra_body["chat_template_kwargs"].get("thinking")
    # OpenClaw path
    if thinking is None and "thinking" in agent_kwargs:
        thinking = agent_kwargs["thinking"]
    # OpenAI reasoning_effort path (e.g. GPT-5.4 xhigh)
    if thinking is None and "reasoning_effort" in agent_kwargs:
        thinking = agent_kwargs["reasoning_effort"]
    # Version: prefer config kwargs, fall back to per-task agent_info / logs
    agent_version = agent_kwargs.get("version")
    if (not agent_version or agent_version == "unknown") and tokens:
        agent_version = tokens.get("ver")

    # Jobs dir from config for run identification
    jobs_dir = config.get("jobs_dir", "")
    cost_usd = _normalize_cost_usd(tokens.get("cost"), config) if tokens else None
    wandb_cost_usd = _calculate_wandb_cost_usd(tokens, model_name, model_display)
    if wandb_cost_usd is not None:
        cost_usd = wandb_cost_usd
    elif not _positive_cost_usd(cost_usd):
        fallback_cost_usd = _calculate_fallback_cost_usd(
            tokens, config, model_name, model_display
        )
        if fallback_cost_usd is not None:
            cost_usd = fallback_cost_usd

    return {
        "vm": vm,
        "run_dir": run_dir,
        "timestamp": timestamp,
        "jobs_dir": jobs_dir,
        "eval_name": eval_name,
        # Agent & model
        "agent": agent_name,
        "model": model_name,
        "model_display": model_display,
        "provider_display": provider_display,
        "vendor_display": vendor_display,
        "agent_version": agent_version,
        "version_display": version_display,
        # Config
        "concurrency": concurrency,
        "env_type": env_type,
        "cpus": cpus,
        "memory_mb": memory_mb,
        "timeout_sec": agent_timeout,
        "timeout_multiplier": config.get("timeout_multiplier"),
        "temperature": temperature,
        "thinking": thinking,
        "thinking_display": thinking_display,
        # Results
        "score": score,
        "n_trials": n_trials,
        "n_scored": eval_data.get("n_trials", n_trials),
        "n_errors": n_errors,
        "n_passed": n_passed,
        "n_failed": n_failed,
        "error_breakdown": error_breakdown,
        "passed_tasks": passed_tasks,
        "failed_tasks": failed_tasks,
        # Timing
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_sec": duration_sec,
        # Token usage (aggregated from per-task results)
        "tokens_in": tokens.get("in") if tokens else None,
        "tokens_out": tokens.get("out") if tokens else None,
        "tokens_cache": tokens.get("cache") if tokens else None,
        "tokens_cache_write": tokens.get("cache_write") if tokens else None,
        "tokens_total": (
            (tokens.get("in") or 0)
            + (tokens.get("cache_write") or 0)
            + (tokens.get("out") or 0)
            if tokens else None
        ),
        "cost_usd": cost_usd,
    }


def collect_vm(vm: str) -> list[dict]:
    """Collect all run results from a single VM."""
    print(f"  Scanning {vm}...", file=sys.stderr)
    run_dirs = find_runs_on_vm(vm)
    if not run_dirs:
        print(f"  [{vm}] No runs found", file=sys.stderr)
        return []

    print(f"  [{vm}] Found {len(run_dirs)} runs", file=sys.stderr)
    results = []
    for run_dir in run_dirs:
        data = read_run_data(vm, run_dir)
        if data:
            record = extract_metrics(vm, run_dir, data["result"], data["config"],
                                    tokens=data.get("tokens"))
            results.append(record)

    print(f"  [{vm}] Collected {len(results)} runs", file=sys.stderr)
    return results


def collect_all(vms: list[str], max_workers: int = 8) -> list[dict]:
    """Collect results from all VMs in parallel."""
    all_results = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(collect_vm, vm): vm for vm in vms}
        for future in as_completed(futures):
            vm = futures[future]
            try:
                results = future.result()
                all_results.extend(results)
            except Exception as e:
                print(f"  [{vm}] Exception: {e}", file=sys.stderr)

    # Sort by timestamp
    all_results.sort(key=lambda r: r.get("timestamp", ""))
    return all_results


def deduplicate(results: list[dict]) -> list[dict]:
    """Remove duplicate runs (same agent+model+timestamp across cloned VMs)."""
    seen = {}
    deduped = []
    for r in results:
        key = (r["agent"], r["model"], r["timestamp"], r["score"])
        if key in seen:
            print(
                f"  Duplicate: {r['vm']}:{r['timestamp']} "
                f"= {seen[key]}:{r['timestamp']}",
                file=sys.stderr,
            )
            continue
        seen[key] = r["vm"]
        deduped.append(r)
    return deduped


# ---------------------------------------------------------------------------
# Local storage — scan, read, and download runs to a local `wolfbench-runs/` directory
# ---------------------------------------------------------------------------

import re as _re

_TIMESTAMP_RE = _re.compile(r"\d{4}-\d{2}-\d{2}__\d{2}-\d{2}-\d{2}$")


def find_local_runs(local_dir) -> list[str]:
    """Find all run directories in local storage.

    Mirrors find_runs_on_vm() but scans the filesystem directly.
    Returns list of absolute path strings.
    """
    local_dir = Path(local_dir)
    if not local_dir.exists():
        return []
    runs = []
    for ts_dir in local_dir.glob("*/*"):
        if (
            ts_dir.is_dir()
            and _TIMESTAMP_RE.match(ts_dir.name)
            and (ts_dir / "result.json").exists()
            and (ts_dir / "config.json").exists()
        ):
            runs.append(str(ts_dir))
    return sorted(runs)


def _read_session_usage(session_path: Path) -> dict | None:
    if not session_path.exists():
        return None
    try:
        first_line = session_path.read_text().splitlines()[0]
        session = json.loads(first_line)
    except (IndexError, json.JSONDecodeError, OSError):
        return None

    input_tokens = session.get("input_tokens") or 0
    output_tokens = session.get("output_tokens") or 0
    cache_read_tokens = session.get("cache_read_tokens") or 0
    cache_write_tokens = session.get("cache_write_tokens") or 0
    actual_cost = session.get("actual_cost_usd")
    estimated_cost = session.get("estimated_cost_usd")
    cost = actual_cost if actual_cost is not None else estimated_cost
    cost = cost or 0
    if not input_tokens and not output_tokens and not cache_read_tokens and not cache_write_tokens and not cost:
        return None

    return {
        "in": input_tokens,
        "out": output_tokens,
        "cache": cache_read_tokens,
        "cache_write": cache_write_tokens,
        "cost": cost,
    }


def _aggregate_local_tokens(run_path) -> dict | None:
    """Aggregate token metrics from per-task result.json files on disk.

    Mirrors the inline Python script in read_run_data() but runs locally.
    """
    run_path = Path(run_path)
    tin = tout = tcache = tcache_write = 0
    cost = 0.0
    ver = None

    # Per-task results live under <task>/result.json (mirrors SSH glob: */result.json)
    task_results = [
        f for f in run_path.glob("*/result.json")
        if f.parent.name not in (".", "__pycache__")
    ]
    if not task_results:
        return None

    for f in task_results:
        try:
            d = json.loads(f.read_text())
            ar = d.get("agent_result") or {}
            task_in = ar.get("n_input_tokens", 0) or 0
            task_out = ar.get("n_output_tokens", 0) or 0
            task_cache = ar.get("n_cache_tokens", 0) or 0
            task_cost = ar.get("cost_usd", 0) or 0
            if not task_in and not task_out and not task_cache and not task_cost:
                session_usage = _read_session_usage(
                    f.parent / "agent" / "hermes-session.jsonl"
                )
                if session_usage:
                    tin += session_usage["in"]
                    tout += session_usage["out"]
                    tcache += session_usage["cache"]
                    tcache_write += session_usage["cache_write"]
                    cost += session_usage["cost"]
                else:
                    tin += task_in
                    tout += task_out
                    tcache += task_cache
                    cost += task_cost
            else:
                tin += task_in
                tout += task_out
                tcache += task_cache
                cost += task_cost
            if ver is None:
                ai = d.get("agent_info") or {}
                v = ai.get("version", "")
                if v and v != "unknown":
                    ver = v
                elif ver is None:
                    cc = f.parent / "agent" / "claude-code.txt"
                    if cc.exists():
                        try:
                            l = cc.read_text().split("\n", 1)[0]
                            ver = json.loads(l).get("claude_code_version") or None
                        except Exception:
                            pass
        except (json.JSONDecodeError, OSError):
            pass

    return {
        "in": tin,
        "out": tout,
        "cache": tcache,
        "cache_write": tcache_write,
        "cost": round(cost, 2),
        "ver": ver,
    }


def read_local_run_data(run_dir: str) -> dict | None:
    """Read result.json, config.json, and aggregate tokens from local storage.

    Mirrors read_run_data() but reads from disk instead of SSH.
    """
    run_path = Path(run_dir)
    try:
        result = json.loads((run_path / "result.json").read_text())
        config = json.loads((run_path / "config.json").read_text())
    except (json.JSONDecodeError, OSError) as e:
        print(f"  [local] Error reading {run_dir}: {e}", file=sys.stderr)
        return None

    tokens = _aggregate_local_tokens(run_path)
    return {"result": result, "config": config, "tokens": tokens}


def collect_local(local_dir) -> list[dict]:
    """Collect all run results from local storage.

    Mirrors collect_vm() but scans a local directory instead of SSH.
    Returns list of flat run records with vm="local".
    """
    local_dir = Path(local_dir)
    if not local_dir.exists():
        return []

    print(f"  Scanning local: {local_dir}...", file=sys.stderr)
    run_dirs = find_local_runs(local_dir)
    if not run_dirs:
        print("  [local] No runs found", file=sys.stderr)
        return []

    print(f"  [local] Found {len(run_dirs)} runs", file=sys.stderr)
    results = []
    for run_dir in run_dirs:
        data = read_local_run_data(run_dir)
        if data:
            record = extract_metrics(
                "local", run_dir, data["result"], data["config"],
                tokens=data.get("tokens"),
            )
            results.append(record)

    print(f"  [local] Collected {len(results)} runs", file=sys.stderr)
    return results


def local_trajectory_counts(run_dir: str | Path) -> tuple[int, int]:
    """Return (trajectory_count, expected_task_count) for a local run cache."""
    run_path = Path(run_dir)
    trajectory_count = sum(1 for _ in run_path.glob("*/agent/trajectory.json"))
    per_task_count = sum(1 for _ in run_path.glob("*/result.json"))
    root_expected = 0
    try:
        result = json.loads((run_path / "result.json").read_text())
        root_expected = (
            result.get("n_total_trials")
            or result.get("stats", {}).get("n_trials")
            or 0
        )
    except (json.JSONDecodeError, OSError):
        pass
    expected_task_count = max(per_task_count, root_expected)
    return trajectory_count, expected_task_count


def local_trajectories_complete(run_dir: str | Path) -> bool:
    """Return True if a local run has a trajectory for every known task."""
    trajectory_count, expected_task_count = local_trajectory_counts(run_dir)
    return expected_task_count > 0 and trajectory_count >= expected_task_count


def download_run(
    vm: str,
    run_dir: str,
    local_base,
    include_trajectories: bool = True,
) -> dict:
    """Download a run directory from a VM to local storage via rsync.

    Returns {"local_path": str|None, "status": "ok"|"skipped"|"error"}.
    """
    import shlex

    local_base = Path(local_base)
    parts = run_dir.rstrip("/").split("/")
    timestamp = parts[-1]
    config_name = parts[-2]
    local_run = local_base / config_name / timestamp

    # Already downloaded?
    if local_run.exists() and (local_run / "result.json").exists():
        if not include_trajectories:
            return {"local_path": str(local_run), "status": "skipped"}
        # Only skip if trajectories are complete, not merely partially present.
        if local_trajectories_complete(local_run):
            return {"local_path": str(local_run), "status": "skipped"}

    local_run.mkdir(parents=True, exist_ok=True)
    remote_shell = "ssh " + " ".join(shlex.quote(opt) for opt in SSH_OPTS)
    source = f"{vm}:{shlex.quote(run_dir.rstrip('/') + '/')}"
    rsync_cmd = [
        "rsync",
        "-az",
        "--partial",
        "--delete-after",
        "--delete-excluded",
        "-e",
        remote_shell,
    ]
    # Keep the local cache to the benchmark evidence WolfBench actually needs.
    # Raw agent workdirs can include gigabytes of temporary binaries per run.
    include_patterns = [
        "*/",
        "result.json",
        "config.json",
        "job.log",
        "exception.txt",
    ]
    if include_trajectories:
        include_patterns.append("trajectory.json")
    for pattern in include_patterns:
        rsync_cmd.append(f"--include={pattern}")
    rsync_cmd.append("--exclude=*")
    rsync_cmd.extend([source, str(local_run) + "/"])
    try:
        proc = subprocess.run(
            rsync_cmd,
            capture_output=True,
            text=True,
            timeout=3600 if include_trajectories else 300,
        )
    except Exception as e:
        print(f"  [{vm}] Download error for {run_dir}: {e}", file=sys.stderr)
        return {"local_path": None, "status": "error"}

    if proc.returncode != 0:
        print(
            f"  [{vm}] Download failed for {run_dir}: {proc.stderr.strip()}",
            file=sys.stderr,
        )
        return {"local_path": None, "status": "error"}

    if include_trajectories and not any(local_run.glob("*/agent/trajectory.json")):
        print(f"  [{vm}] Download missing trajectories for {run_dir}", file=sys.stderr)
        return {"local_path": None, "status": "error"}

    # Write provenance metadata
    meta = {
        "source_vm": vm,
        "source_run_dir": run_dir,
        "downloaded_at": datetime.now().isoformat(),
        "has_trajectories": bool(any(local_run.glob("*/agent/trajectory.json"))),
        "download_mode": "full" if include_trajectories else "meta",
    }
    try:
        with open(local_run / "_meta.json", "w") as f:
            json.dump(meta, f, indent=2)
    except OSError:
        pass

    return {"local_path": str(local_run), "status": "ok"}


def download_runs(
    runs: list[dict],
    local_base,
    include_trajectories: bool = True,
    max_workers: int = 4,
    progress_callback=None,
) -> list[dict]:
    """Download multiple runs from VMs to local storage in parallel.

    Each run dict must have 'vm' and 'run_dir' keys.
    Returns list of dicts: [{"run": run, "local_path": ..., "status": ...}].
    """
    local_base = Path(local_base)
    local_base.mkdir(parents=True, exist_ok=True)
    results = []

    def _dl(run):
        return {
            "run": run,
            **download_run(run["vm"], run["run_dir"], local_base, include_trajectories),
        }

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_dl, r): r for r in runs}
        for future in as_completed(futures):
            run = futures[future]
            try:
                result = future.result()
                results.append(result)
                msg = f"  [{run['vm']}] {run['timestamp']}: {result['status']}"
                print(msg, file=sys.stderr)
                if progress_callback:
                    progress_callback(msg)
            except Exception as e:
                results.append({"run": run, "local_path": None, "status": "error"})
                print(f"  [{run['vm']}] {run['timestamp']}: error — {e}", file=sys.stderr)

    return results


EXPECTED_TASKS = 89  # Terminal-Bench 2.0 full benchmark


def classify_run(run: dict) -> str | None:
    """Classify a run as valid or return an exclude reason.

    Returns None if valid, or a string explaining why excluded.
    """
    n_trials = run.get("n_trials", 0)
    n_errors = run.get("n_errors", 0)
    eval_name = run.get("eval_name", "")

    # Not the full benchmark (partials, samples, tests)
    if n_trials < EXPECTED_TASKS:
        if "sample" in eval_name or "sample" in run.get("jobs_dir", ""):
            return f"sample run ({n_trials}/{EXPECTED_TASKS} tasks)"
        if n_trials <= 10:
            return f"test run ({n_trials} tasks)"
        return f"partial run ({n_trials}/{EXPECTED_TASKS} tasks)"

    # All tasks errored — total infra failure
    if n_trials > 0 and n_errors == n_trials:
        return f"total failure ({n_errors}/{n_trials} errors)"

    return None


def split_runs(results: list[dict]) -> tuple[list[dict], list[dict]]:
    """Split runs into (valid, excluded) based on classification."""
    valid = []
    excluded = []
    for run in results:
        reason = classify_run(run)
        if reason is None:
            valid.append(run)
        else:
            run_with_reason = {**run, "exclude_reason": reason}
            excluded.append(run_with_reason)
    return valid, excluded


def print_table(results: list[dict]):
    """Print a human-readable summary table."""
    # Header
    print(f"\n{'Date':<12} {'Agent':<12} {'Model':<28} {'Score':>7} "
          f"{'Pass':>4}/{'':<4} {'Err':>3} {'Conc':>4} {'RAM':>6} "
          f"{'Timeout':>8} {'Duration':>10} {'VM'}")
    print("-" * 140)

    for r in results:
        date = r["timestamp"][:10] if r["timestamp"] else "?"
        agent = r["agent"][:12]
        model = r["model_display"][:28]
        score = f"{r['score']:.1%}" if r["score"] is not None else "?"
        n_pass = r["n_passed"]
        n_total = r["n_trials"]
        n_err = r["n_errors"]
        conc = str(r["concurrency"] or "?")
        ram = f"{r['memory_mb']}MB" if r["memory_mb"] else "?"
        timeout = f"{int(r['timeout_sec'])}s" if r["timeout_sec"] else "default"
        if r["duration_sec"]:
            h, rem = divmod(int(r["duration_sec"]), 3600)
            m, s = divmod(rem, 60)
            duration = f"{h}h{m:02d}m"
        else:
            duration = "?"
        vm_short = r["vm"].replace(".exe.xyz", "").replace("harbor-evals-", "h-e-")

        print(f"{date:<12} {agent:<12} {model:<28} {score:>7} "
              f"{n_pass:>4}/{n_total:<4} {n_err:>3} {conc:>4} {ram:>6} "
              f"{timeout:>8} {duration:>10} {vm_short}")


def print_leaderboard(results: list[dict]):
    """Print aggregated leaderboard grouped by agent+model."""
    groups = {}
    for r in results:
        key = (r["agent"], r["model_display"])
        if key not in groups:
            groups[key] = []
        groups[key].append(r)

    print(f"\n{'Agent':<12} {'Model':<28} {'Runs':>4} {'Best':>7} "
          f"{'Avg':>7} {'Worst':>7} {'Ceiling':>7}")
    print("-" * 90)

    # Sort by best score descending
    sorted_groups = sorted(
        groups.items(),
        key=lambda x: max(r["score"] for r in x[1] if r["score"] is not None),
        reverse=True,
    )

    for (agent, model), runs in sorted_groups:
        scores = [r["score"] for r in runs if r["score"] is not None]
        if not scores:
            continue

        # Ceiling: union of all passed tasks across runs
        all_passed = set()
        for r in runs:
            all_passed.update(r.get("passed_tasks", []))
        total_tasks = max(r["n_trials"] for r in runs)
        ceiling = len(all_passed) / total_tasks if total_tasks > 0 else 0

        best = max(scores)
        avg = sum(scores) / len(scores)
        worst = min(scores)

        print(f"{agent:<12} {model:<28} {len(runs):>4} {best:>7.1%} "
              f"{avg:>7.1%} {worst:>7.1%} {ceiling:>7.1%}")


def main():
    parser = argparse.ArgumentParser(
        description="Collect Harbor eval results from exe.dev VMs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "-o", "--output",
        type=Path,
        default=Path(__file__).parent / "wolfbench_results.json",
        help="Output JSON file for valid runs (default: wolfbench_results.json)",
    )
    parser.add_argument(
        "--excluded-output",
        type=Path,
        default=None,
        help="Output JSON file for excluded runs (default: <output>_excluded.json)",
    )
    parser.add_argument(
        "--table", action="store_true",
        help="Print human-readable summary table",
    )
    parser.add_argument(
        "--leaderboard", action="store_true",
        help="Print aggregated leaderboard by agent+model",
    )
    parser.add_argument(
        "--vms", nargs="+",
        help="Override VM list (space-separated hostnames)",
    )
    parser.add_argument(
        "--workers", type=int, default=8,
        help="Max parallel SSH connections (default: 8)",
    )
    parser.add_argument(
        "--no-dedup", action="store_true",
        help="Don't remove duplicate runs from cloned VMs",
    )
    parser.add_argument(
        "--json-only", action="store_true",
        help="Output only the JSON to stdout (no progress, no table)",
    )
    args = parser.parse_args()

    # Determine VM list
    if args.vms:
        vms = args.vms
    else:
        vms = discover_vms()

    if not args.json_only:
        print(f"Collecting results from {len(vms)} VMs...", file=sys.stderr)

    # Collect
    results = collect_all(vms, max_workers=args.workers)

    if not args.json_only:
        print(f"\nCollected {len(results)} total runs", file=sys.stderr)

    # Deduplicate
    if not args.no_dedup:
        results = deduplicate(results)
        if not args.json_only:
            print(f"After dedup: {len(results)} unique runs", file=sys.stderr)

    # Split into valid and excluded
    valid, excluded = split_runs(results)
    if not args.json_only:
        print(f"Valid runs: {len(valid)}, Excluded: {len(excluded)}", file=sys.stderr)
        for r in excluded:
            print(f"  excluded: {r['timestamp']} {r['agent']:>12} "
                  f"{r['model_display']:>20} — {r['exclude_reason']}", file=sys.stderr)

    # Derive excluded output path
    excluded_output = args.excluded_output
    if excluded_output is None:
        excluded_output = args.output.with_name(
            args.output.stem + "_excluded" + args.output.suffix
        )

    now = datetime.now().isoformat()

    valid_data = {
        "collected_at": now,
        "n_vms": len(vms),
        "n_runs": len(valid),
        "benchmark": "terminal-bench-2.0",
        "expected_tasks": EXPECTED_TASKS,
        "vms": vms,
        "runs": valid,
    }

    excluded_data = {
        "collected_at": now,
        "n_vms": len(vms),
        "n_runs": len(excluded),
        "vms": vms,
        "runs": excluded,
    }

    if args.json_only:
        json.dump(valid_data, sys.stdout, indent=2)
    else:
        with open(args.output, "w") as f:
            json.dump(valid_data, f, indent=2)
        with open(excluded_output, "w") as f:
            json.dump(excluded_data, f, indent=2)
        print(f"Written valid   → {args.output}", file=sys.stderr)
        print(f"Written excluded → {excluded_output}", file=sys.stderr)

    # Print tables (valid runs only)
    if args.table or (not args.json_only and not args.leaderboard):
        print_table(valid)

    if args.leaderboard:
        print_leaderboard(valid)


if __name__ == "__main__":
    main()
