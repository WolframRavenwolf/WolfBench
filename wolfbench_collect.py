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
import inspect
import json
import shlex
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
    # Anthropic first-party Sonnet 5 introductory API pricing through
    # 2026-08-31. Uses the 5-minute cache-write rate because Harbor's
    # model_info field stores one cache creation price.
    "anthropic-claude-sonnet-5-intro": {
        "input": 2.00,
        "cache_read": 0.20,
        "cache_creation": 2.50,
        "output": 10.00,
    },
    "anthropic-claude-sonnet-5": {
        "input": 3.00,
        "cache_read": 0.30,
        "cache_creation": 3.75,
        "output": 15.00,
    },
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
    "anthropic/claude-sonnet-5": "anthropic-claude-sonnet-5",
    "claude sonnet 5": "anthropic-claude-sonnet-5",
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
    # Ship the same stdlib-only aggregation helpers used locally so remote and
    # downloaded runs cannot drift into different token-accounting dialects.
    helper_names = (
        "_read_json_file",
        "_read_session_usage",
        "_read_openclaw_usage",
        "_read_claude_code_usage",
        "_read_cursor_usage",
        "_model_info_rates_per_token",
        "_model_supports_cache_writes",
        "_infer_cache_write_from_cost",
        "_generic_task_usage",
        "_task_usage",
        "_aggregate_local_tokens",
    )
    token_script = (
        "from __future__ import annotations\n"
        "import json,sys\nfrom pathlib import Path\n"
        "COST_PER_MILLION_SCALE = 1000000\n\n"
        + "\n\n".join(
        inspect.getsource(globals()[name]) for name in helper_names
        )
    )
    token_script += "\nprint(json.dumps(_aggregate_local_tokens(Path(sys.argv[1]))))\n"
    command = (
        f'cat "{run_dir}/result.json" && echo "---JSON_SEPARATOR---" && '
        f'cat "{run_dir}/config.json" && echo "---JSON_SEPARATOR---" && '
        f"python3 -c {shlex.quote(token_script)} {shlex.quote(run_dir)}"
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


def _run_date_from_timestamp(timestamp: str | None):
    if not timestamp:
        return None
    try:
        return datetime.fromisoformat(str(timestamp)[:10]).date()
    except (TypeError, ValueError):
        return None


def _config_uses_us_inference_geo(config: dict | None) -> bool:
    if not isinstance(config, dict):
        return False

    stack = [config]
    while stack:
        value = stack.pop()
        if isinstance(value, dict):
            for key, child in value.items():
                if key == "inference_geo" and str(child).lower() == "us":
                    return True
                stack.append(child)
        elif isinstance(value, list):
            stack.extend(value)
    return False


def _pricing_with_multiplier(pricing: dict, multiplier: float) -> dict:
    return {
        key: (value * multiplier if value is not None else None)
        for key, value in pricing.items()
    }


def _authoritative_pricing_for_model(
    model_name: str,
    model_display: str,
    timestamp: str | None,
    config: dict | None = None,
) -> dict | None:
    candidates = [
        str(value or "").strip().lower()
        for value in (model_name, model_display)
    ]
    is_sonnet5 = any(
        "claude-sonnet-5" in candidate or candidate == "claude sonnet 5"
        for candidate in candidates
    )
    if not is_sonnet5:
        return None

    run_date = _run_date_from_timestamp(timestamp)
    if run_date is not None and run_date < datetime(2026, 9, 1).date():
        pricing = TOKEN_PRICING_PER_1M["anthropic-claude-sonnet-5-intro"]
    else:
        pricing = TOKEN_PRICING_PER_1M["anthropic-claude-sonnet-5"]

    if _config_uses_us_inference_geo(config):
        return _pricing_with_multiplier(pricing, 1.1)
    return pricing


def _calculate_authoritative_cost_usd(
    tokens: dict | None,
    model_name: str,
    model_display: str,
    timestamp: str | None,
    config: dict | None = None,
):
    pricing = _authoritative_pricing_for_model(
        model_name, model_display, timestamp, config
    )
    return _calculate_token_cost_usd(tokens, pricing)


def _split_uncached_and_cached_input(input_tokens, cache_tokens) -> tuple[float, float]:
    input_tokens = input_tokens or 0
    cache_tokens = cache_tokens or 0
    if cache_tokens and input_tokens >= cache_tokens:
        return input_tokens - cache_tokens, cache_tokens
    return input_tokens, cache_tokens


def _calculate_token_cost_usd(tokens: dict | None, pricing: dict | None):
    if not tokens or not pricing:
        return None

    cache_tokens = tokens.get("cache") or 0
    output_tokens = tokens.get("out") or 0
    input_rate = pricing["input"]
    cache_rate = pricing.get("cache_read")
    if cache_rate is None:
        cache_rate = input_rate
    cache_creation_rate = pricing.get("cache_creation")
    if cache_creation_rate is None:
        cache_creation_rate = input_rate

    if "non_cached" in tokens or "uncached" in tokens:
        uncached_input_tokens = tokens.get("uncached")
        cache_creation_tokens = tokens.get("cache_write")
        if uncached_input_tokens is None or cache_creation_tokens is None:
            # Cache writes have a distinct price. Unknown historical writes must
            # not silently become zero and produce a deceptively precise cost.
            if pricing.get("cache_creation") is not None:
                return None
            uncached_input_tokens = tokens.get("non_cached") or 0
            cache_creation_tokens = 0
        cached_input_tokens = cache_tokens
        uncached_input_rate = input_rate
    else:
        # Backward compatibility for pre-v2 snapshots whose `in` field mixed
        # subset and separate cache dialects.
        input_tokens = tokens.get("in") or 0
        cache_write_tokens = tokens.get("cache_write") or 0
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

    if not uncached_input_tokens and not cached_input_tokens and not cache_creation_tokens and not output_tokens:
        return None

    cost = (
        uncached_input_tokens * uncached_input_rate
        + cache_creation_tokens * cache_creation_rate
        + cached_input_tokens * cache_rate
        + output_tokens * pricing["output"]
    ) / COST_PER_MILLION_SCALE
    return round(cost, 2)


def _calculate_token_cost_bounds_usd(
    tokens: dict | None,
    pricing: dict | None,
) -> tuple[float, float] | None:
    """Bound token cost when the uncached/cache-write split is unknown.

    Token accounting v2 reports cache reads as a subset of total input. The
    remaining non-cached input is therefore known even when the agent does not
    expose how much of it was ordinary uncached input versus cache creation.
    Price both extreme allocations to preserve an honest lower/upper bound.
    """
    if not tokens or not pricing:
        return None
    if tokens.get("usage_complete") is False:
        return None
    if "non_cached" not in tokens and "uncached" not in tokens:
        return None

    input_tokens = tokens.get("in")
    if input_tokens is None:
        return None
    input_tokens = max(float(input_tokens), 0.0)
    cache_tokens = min(max(float(tokens.get("cache") or 0), 0.0), input_tokens)
    output_tokens = max(float(tokens.get("out") or 0), 0.0)

    non_cached_tokens = tokens.get("non_cached")
    if non_cached_tokens is None:
        non_cached_tokens = input_tokens - cache_tokens
    non_cached_tokens = float(non_cached_tokens)
    if non_cached_tokens < 0 or non_cached_tokens > input_tokens - cache_tokens + 0.5:
        return None

    input_rate = float(pricing["input"])
    cache_read_value = pricing.get("cache_read")
    cache_creation_value = pricing.get("cache_creation")
    cache_read_rate = float(
        input_rate if cache_read_value is None else cache_read_value
    )
    cache_creation_rate = float(
        input_rate if cache_creation_value is None else cache_creation_value
    )
    output_rate = float(pricing["output"])

    uncached_tokens = tokens.get("uncached")
    cache_write_tokens = tokens.get("cache_write")
    if uncached_tokens is not None:
        uncached_tokens = float(uncached_tokens)
    if cache_write_tokens is not None:
        cache_write_tokens = float(cache_write_tokens)

    if uncached_tokens is not None and cache_write_tokens is None:
        cache_write_tokens = non_cached_tokens - uncached_tokens
    elif cache_write_tokens is not None and uncached_tokens is None:
        uncached_tokens = non_cached_tokens - cache_write_tokens

    fixed_cost = cache_tokens * cache_read_rate + output_tokens * output_rate
    if uncached_tokens is not None and cache_write_tokens is not None:
        if uncached_tokens < 0 or cache_write_tokens < 0:
            return None
        if abs((uncached_tokens + cache_write_tokens) - non_cached_tokens) > 0.5:
            return None
        cost = (
            fixed_cost
            + uncached_tokens * input_rate
            + cache_write_tokens * cache_creation_rate
        ) / COST_PER_MILLION_SCALE
        rounded = round(cost, 8)
        return rounded, rounded

    low_rate = min(input_rate, cache_creation_rate)
    high_rate = max(input_rate, cache_creation_rate)
    low = (fixed_cost + non_cached_tokens * low_rate) / COST_PER_MILLION_SCALE
    high = (fixed_cost + non_cached_tokens * high_rate) / COST_PER_MILLION_SCALE
    if high <= 0:
        return None
    return round(low, 8), round(high, 8)


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


def _pricing_for_cost_bounds(
    config: dict,
    model_name: str,
    model_display: str,
    timestamp: str | None,
) -> dict | None:
    """Select the same highest-priority token rates used for exact costs."""
    return (
        _authoritative_pricing_for_model(
            model_name, model_display, timestamp, config
        )
        or _wandb_pricing_for_model(model_name, model_display)
        or _pricing_from_model_info(config)
        or _fallback_pricing_for_model(model_name, model_display)
    )


def _first_available_count(*values):
    """Return the first count present in a sequence, preserving zero."""
    for value in values:
        if value is not None:
            return value
    return 0


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

    # Result metrics. Harbor 0.18 renamed the top-level stats counters from
    # n_trials/n_errors to n_completed_trials/n_errored_trials while retaining
    # eval-level counters and n_total_trials. Prefer completed work over the
    # planned total so partial runs remain partial in WolfBench.
    stats = result.get("stats", {})
    evals = stats.get("evals", {})
    eval_name = next(iter(evals), "")
    eval_data = evals.get(eval_name, {})
    n_trials = _first_available_count(
        stats.get("n_trials"),
        stats.get("n_completed_trials"),
        eval_data.get("n_trials"),
        result.get("n_total_trials"),
    )
    n_errors = _first_available_count(
        stats.get("n_errors"),
        stats.get("n_errored_trials"),
        eval_data.get("n_errors"),
    )

    # Score from evals — take first eval's first metric mean
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
    authoritative_cost_usd = _calculate_authoritative_cost_usd(
        tokens, model_name, model_display, timestamp, config
    )
    wandb_cost_usd = _calculate_wandb_cost_usd(tokens, model_name, model_display)
    if authoritative_cost_usd is not None:
        cost_usd = authoritative_cost_usd
    elif wandb_cost_usd is not None:
        cost_usd = wandb_cost_usd
    elif not _positive_cost_usd(cost_usd):
        fallback_cost_usd = _calculate_fallback_cost_usd(
            tokens, config, model_name, model_display
        )
        if fallback_cost_usd is not None:
            cost_usd = fallback_cost_usd

    cost_usd_min = None
    cost_usd_max = None
    cost_usd_estimated = False
    cost_usd_basis = None
    if not _positive_cost_usd(cost_usd):
        cost_bounds = _calculate_token_cost_bounds_usd(
            tokens,
            _pricing_for_cost_bounds(
                config, model_name, model_display, timestamp
            ),
        )
        if cost_bounds is not None:
            cost_usd_min, cost_usd_max = cost_bounds
            cost_usd_estimated = True
            cost_usd_basis = "token_rate_bounds_missing_cache_write_split"

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
        # Token usage v2: `tokens_in` is total input, including cache writes and
        # reads. The component fields are non-overlapping.
        "token_accounting_version": 2,
        "tokens_in": tokens.get("in") if tokens else None,
        "tokens_input_uncached": tokens.get("uncached") if tokens else None,
        "tokens_input_non_cached": tokens.get("non_cached") if tokens else None,
        "tokens_out": tokens.get("out") if tokens else None,
        "tokens_cache": tokens.get("cache") if tokens else None,
        "tokens_cache_read": tokens.get("cache") if tokens else None,
        "tokens_cache_write": tokens.get("cache_write") if tokens else None,
        "token_usage_complete": tokens.get("usage_complete") if tokens else False,
        "cache_write_complete": tokens.get("cache_write_complete") if tokens else False,
        "token_tasks": tokens.get("tasks") if tokens else None,
        "tokens_total": (
            (tokens.get("in") or 0)
            + (tokens.get("out") or 0)
            if tokens and tokens.get("in") is not None else None
        ),
        "cost_usd": cost_usd,
        "cost_usd_min": cost_usd_min,
        "cost_usd_max": cost_usd_max,
        "cost_usd_estimated": cost_usd_estimated,
        "cost_usd_basis": cost_usd_basis,
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


def _read_json_file(path: Path) -> dict | list | None:
    try:
        with path.open() as handle:
            return json.load(handle)
    except (json.JSONDecodeError, OSError, TypeError):
        return None


def _read_session_usage(session_path: Path) -> dict | None:
    """Read Hermes' first-line cumulative usage summary."""
    try:
        with session_path.open() as handle:
            session = json.loads(handle.readline())
    except (json.JSONDecodeError, OSError, TypeError):
        return None

    uncached = session.get("input_tokens") or 0
    output = session.get("output_tokens") or 0
    cache_read = session.get("cache_read_tokens") or 0
    cache_write = session.get("cache_write_tokens") or 0
    actual_cost = session.get("actual_cost_usd")
    estimated_cost = session.get("estimated_cost_usd")
    cost = actual_cost if actual_cost is not None else estimated_cost
    cost = cost or 0
    if not uncached and not output and not cache_read and not cache_write and not cost:
        return None

    return {
        "uncached": uncached,
        "out": output,
        "cache": cache_read,
        "cache_write": cache_write,
        "cost": cost,
    }


def _read_openclaw_usage(agent_dir: Path, expected: dict | None = None) -> dict | None:
    """Read the canonical or timeout-fallback OpenClaw session."""
    canonical = agent_dir / "openclaw-session.jsonl"
    candidates = [canonical] if canonical.exists() else []
    candidates.extend(sorted((agent_dir / "openclaw-sessions").glob("*.jsonl")))
    usages = []
    for session_path in candidates:
        uncached = output = cache_read = cache_write = 0
        found = False
        try:
            with session_path.open() as handle:
                for line in handle:
                    try:
                        event = json.loads(line)
                    except (json.JSONDecodeError, TypeError):
                        continue
                    message = event.get("message") or {}
                    usage = message.get("usage") or event.get("usage")
                    if not isinstance(usage, dict):
                        continue
                    found = True
                    uncached += usage.get("input", 0) or 0
                    output += usage.get("output", 0) or 0
                    cache_read += usage.get("cacheRead", 0) or 0
                    cache_write += usage.get("cacheWrite", 0) or 0
        except OSError:
            continue
        if found:
            usages.append({
                "uncached": uncached,
                "out": output,
                "cache": cache_read,
                "cache_write": cache_write,
            })

    if expected:
        for usage in usages:
            if all(
                not expected.get(key) or usage[value_key] == expected[key]
                for key, value_key in (
                    ("in", "uncached"),
                    ("out", "out"),
                    ("cache", "cache"),
                )
            ):
                return usage
    return max(
        usages,
        key=lambda usage: usage["uncached"] + usage["out"] + usage["cache"] + usage["cache_write"],
        default=None,
    )


def _read_claude_code_usage(agent_dir: Path) -> dict | None:
    """Recover Claude Code cache reads/writes from trajectories or raw output."""
    trajectory = _read_json_file(agent_dir / "trajectory.json")
    if isinstance(trajectory, dict):
        cache_read = cache_write = 0
        found = False
        for step in trajectory.get("steps") or []:
            metrics = step.get("metrics") or {}
            extra = metrics.get("extra") or {}
            if not isinstance(extra, dict):
                continue
            if "cache_read_input_tokens" not in extra and "cache_creation_input_tokens" not in extra:
                continue
            found = True
            cache_read += extra.get("cache_read_input_tokens", 0) or 0
            cache_write += extra.get("cache_creation_input_tokens", 0) or 0
        if found:
            return {"cache": cache_read, "cache_write": cache_write}

    raw_path = agent_dir / "claude-code.txt"
    latest = None
    try:
        with raw_path.open() as handle:
            for line in handle:
                try:
                    event = json.loads(line)
                except (json.JSONDecodeError, TypeError):
                    continue
                usage = event.get("usage")
                if isinstance(usage, dict):
                    latest = usage
    except OSError:
        return None
    if not latest:
        return None
    return {
        "uncached": latest.get("input_tokens", 0) or 0,
        "out": latest.get("output_tokens", 0) or 0,
        "cache": latest.get("cache_read_input_tokens", 0) or 0,
        "cache_write": latest.get("cache_creation_input_tokens", 0) or 0,
    }


def _read_cursor_usage(raw_path: Path) -> dict | None:
    """Read Cursor CLI's final cumulative result usage."""
    latest = None
    try:
        with raw_path.open() as handle:
            for line in handle:
                try:
                    event = json.loads(line)
                except (json.JSONDecodeError, TypeError):
                    continue
                usage = event.get("usage")
                if isinstance(usage, dict):
                    latest = usage
    except OSError:
        return None
    if not latest:
        return None
    return {
        "uncached": latest.get("inputTokens", 0) or 0,
        "out": latest.get("outputTokens", 0) or 0,
        "cache": latest.get("cacheReadTokens", 0) or 0,
        "cache_write": latest.get("cacheWriteTokens", 0) or 0,
    }


def _model_info_rates_per_token(config: dict) -> dict | None:
    model_info = ((config.get("agents") or [{}])[0].get("kwargs") or {}).get("model_info") or {}

    def rate(key):
        try:
            value = float(model_info.get(key))
        except (TypeError, ValueError):
            return None
        if value <= 0:
            return None
        return value / COST_PER_MILLION_SCALE if value >= 0.001 else value

    rates = {
        "input": rate("input_cost_per_token"),
        "output": rate("output_cost_per_token"),
        "cache_read": rate("cache_read_input_token_cost"),
        "cache_write": rate("cache_creation_input_token_cost"),
    }
    return rates if rates["input"] and rates["output"] else None


def _model_supports_cache_writes(config: dict) -> bool:
    agent_cfg = (config.get("agents") or [{}])[0]
    kwargs = agent_cfg.get("kwargs") or {}
    model_info = kwargs.get("model_info") or {}
    values = (
        agent_cfg.get("model_name"),
        model_info.get("name"),
        model_info.get("provider"),
    )
    is_anthropic = any(
        "anthropic" in str(value or "").lower()
        or "claude" in str(value or "").lower()
        for value in values
    )
    return bool(model_info.get("cache_creation_input_token_cost")) or is_anthropic


def _infer_cache_write_from_cost(task_in, task_cache, task_out, task_cost, config):
    """Recover an exact cache-write count when recorded cost makes it solvable."""
    rates = _model_info_rates_per_token(config)
    if not rates or not task_cost or rates.get("cache_read") is None or rates.get("cache_write") is None:
        return None

    input_rate = rates["input"]
    output_rate = rates["output"]
    read_rate = rates["cache_read"]
    write_rate = rates["cache_write"]
    if write_rate == input_rate:
        return None

    if task_in >= task_cache:
        non_cached = task_in - task_cache
        numerator = (
            task_cost
            - non_cached * input_rate
            - task_cache * read_rate
            - task_out * output_rate
        )
        cache_write = numerator / (write_rate - input_rate)
        max_write = non_cached
        total_input = task_in
    else:
        numerator = (
            task_cost
            - task_in * input_rate
            - task_cache * read_rate
            - task_out * output_rate
        )
        cache_write = numerator / write_rate
        max_write = None
        total_input = task_in + task_cache + cache_write

    rounded_write = round(cache_write)
    if abs(cache_write - rounded_write) > 0.001 or rounded_write < 0:
        return None
    if max_write is not None and rounded_write > max_write:
        return None

    uncached = (task_in - task_cache - rounded_write) if task_in >= task_cache else task_in
    reconstructed = (
        uncached * input_rate
        + rounded_write * write_rate
        + task_cache * read_rate
        + task_out * output_rate
    )
    if abs(reconstructed - task_cost) > max(1e-8, abs(task_cost) * 1e-8):
        return None
    return {
        "in": round(total_input),
        "uncached": round(uncached),
        "non_cached": round(uncached + rounded_write),
        "cache": round(task_cache),
        "cache_write": rounded_write,
        "out": round(task_out),
        "usage_complete": True,
        "cache_write_complete": True,
    }


def _generic_task_usage(task_in, task_cache, task_out, task_cost, config):
    if not task_in and not task_cache and not task_out and not task_cost:
        return {
            "in": 0,
            "input_lower_bound": 0,
            "uncached": 0,
            "non_cached": 0,
            "cache": 0,
            "cache_write": 0,
            "out": 0,
            "usage_complete": True,
            "cache_write_complete": True,
        }

    inferred = _infer_cache_write_from_cost(
        task_in, task_cache, task_out, task_cost, config
    )
    if inferred:
        return inferred

    has_cache_writes = _model_supports_cache_writes(config)
    if task_in >= task_cache:
        total_input = task_in
        non_cached = task_in - task_cache
        usage_complete = True
    else:
        total_input = task_in + task_cache
        non_cached = task_in
        usage_complete = not has_cache_writes

    return {
        "in": total_input if usage_complete else None,
        "input_lower_bound": task_in + task_cache,
        "uncached": non_cached if not has_cache_writes else None,
        "non_cached": non_cached if usage_complete else None,
        "cache": task_cache,
        "cache_write": 0 if not has_cache_writes else None,
        "out": task_out,
        "usage_complete": usage_complete,
        "cache_write_complete": not has_cache_writes,
    }


def _task_usage(task_dir: Path, task_result: dict, config: dict) -> dict:
    agent_cfg = (config.get("agents") or [{}])[0]
    agent_name = str(agent_cfg.get("name") or "").lower()
    ar = task_result.get("agent_result") or {}
    task_in = ar.get("n_input_tokens", 0) or 0
    task_out = ar.get("n_output_tokens", 0) or 0
    task_cache = ar.get("n_cache_tokens", 0) or 0
    task_cost = ar.get("cost_usd", 0) or 0
    agent_dir = task_dir / "agent"

    if agent_name == "hermes":
        native = _read_session_usage(agent_dir / "hermes-session.jsonl")
        if native:
            uncached = native["uncached"]
            cache_read = native["cache"]
            cache_write = native["cache_write"]
            return {
                "in": uncached + cache_read + cache_write,
                "uncached": uncached,
                "non_cached": uncached + cache_write,
                "cache": cache_read,
                "cache_write": cache_write,
                "out": native["out"],
                "cost": native.get("cost") or task_cost,
                "usage_complete": True,
                "cache_write_complete": True,
            }

    if agent_name == "openclaw":
        native = _read_openclaw_usage(
            agent_dir,
            {"in": task_in, "out": task_out, "cache": task_cache},
        )
        if native:
            counters_match = (
                (not task_in or native["uncached"] == task_in)
                and (not task_out or native["out"] == task_out)
                and (not task_cache or native["cache"] == task_cache)
            )
            if counters_match:
                uncached = native["uncached"]
                cache_read = native["cache"]
                cache_write = native["cache_write"]
                return {
                    "in": uncached + cache_read + cache_write,
                    "uncached": uncached,
                    "non_cached": uncached + cache_write,
                    "cache": cache_read,
                    "cache_write": cache_write,
                    "out": native["out"],
                    "cost": task_cost,
                    "usage_complete": True,
                    "cache_write_complete": True,
                }

    if agent_name == "claude-code":
        native = _read_claude_code_usage(agent_dir)
        if native and (not task_cache or native["cache"] == task_cache):
            cache_read = native["cache"]
            cache_write = native["cache_write"]
            if native.get("uncached") is not None:
                uncached = native["uncached"]
                output = native.get("out") if native.get("out") is not None else task_out
            elif task_in >= cache_read:
                uncached = task_in - cache_read
                output = task_out
            else:
                uncached = None
                output = task_out
            if uncached is not None:
                return {
                    "in": uncached + cache_read + cache_write,
                    "uncached": uncached,
                    "non_cached": uncached + cache_write,
                    "cache": cache_read,
                    "cache_write": cache_write,
                    "out": output,
                    "cost": task_cost,
                    "usage_complete": True,
                    "cache_write_complete": True,
                }

    if agent_name == "cursor-cli":
        native = _read_cursor_usage(agent_dir / "cursor-cli.txt")
        if native:
            uncached = native["uncached"]
            cache_read = native["cache"]
            cache_write = native["cache_write"]
            output = native["out"]
            counters_match = (
                (not task_in or uncached + cache_read + cache_write == task_in)
                and (not task_out or output == task_out)
                and (not task_cache or cache_read == task_cache)
            )
            if counters_match:
                return {
                    "in": uncached + cache_read + cache_write,
                    "uncached": uncached,
                    "non_cached": uncached + cache_write,
                    "cache": cache_read,
                    "cache_write": cache_write,
                    "out": output,
                    "cost": task_cost,
                    "usage_complete": True,
                    "cache_write_complete": True,
                }

    usage = _generic_task_usage(
        task_in, task_cache, task_out, task_cost, config
    )
    usage["cost"] = task_cost
    return usage


def _aggregate_local_tokens(run_path) -> dict | None:
    """Aggregate token metrics from per-task result.json files on disk.

    Mirrors the inline Python script in read_run_data() but runs locally.
    """
    run_path = Path(run_path)
    config = _read_json_file(run_path / "config.json")
    if not isinstance(config, dict):
        return None

    tin = tuncached = tnon_cached = tout = tcache = tcache_write = 0
    input_lower_bound = 0
    cost = 0.0
    ver = None
    usage_complete = True
    uncached_complete = True
    non_cached_complete = True
    cache_write_complete = True
    task_count = 0

    # Per-task results live under <task>/result.json (mirrors SSH glob: */result.json)
    task_results = [
        f for f in run_path.glob("*/result.json")
        if f.parent.name not in (".", "__pycache__")
    ]
    if not task_results:
        return None

    for f in task_results:
        try:
            d = _read_json_file(f)
            if not isinstance(d, dict):
                usage_complete = uncached_complete = False
                non_cached_complete = cache_write_complete = False
                continue
            task_count += 1
            usage = _task_usage(f.parent, d, config)
            task_input = usage.get("in")
            task_uncached = usage.get("uncached")
            task_non_cached = usage.get("non_cached")
            task_cache_write = usage.get("cache_write")
            input_lower_bound += usage.get("input_lower_bound") or task_input or 0
            if task_input is None:
                usage_complete = False
            else:
                tin += task_input
            if task_uncached is None:
                uncached_complete = False
            else:
                tuncached += task_uncached
            if task_non_cached is None:
                non_cached_complete = False
            else:
                tnon_cached += task_non_cached
            if task_cache_write is None:
                cache_write_complete = False
            else:
                tcache_write += task_cache_write
            tout += usage.get("out") or 0
            tcache += usage.get("cache") or 0
            cost += usage.get("cost") or 0
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
        except (OSError, TypeError, ValueError):
            usage_complete = uncached_complete = False
            non_cached_complete = cache_write_complete = False

    return {
        "in": tin if usage_complete else None,
        "input_lower_bound": input_lower_bound,
        "uncached": tuncached if uncached_complete else None,
        "non_cached": tnon_cached if non_cached_complete else None,
        "out": tout,
        "cache": tcache,
        "cache_write": tcache_write if cache_write_complete else None,
        "cost": round(cost, 8),
        "ver": ver,
        "usage_complete": usage_complete,
        "cache_write_complete": cache_write_complete,
        "tasks": task_count,
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
