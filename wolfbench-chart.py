#!/usr/bin/env python3
"""WolfBench Chart — HTML/CSS Chart Generator.

Generates a WolfBench chart as a standalone HTML file with metallic-gradient
bars per model/agent, using the Five-Metric Framework.

Usage:
    python wolfbench-chart.py                    # Generate wolfbench.html
    python wolfbench-chart.py -i results.json    # Custom input
    python wolfbench-chart.py --min-runs 3       # Require ≥3 runs
"""

from __future__ import annotations

import argparse
import base64
import json
import re
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from html import escape as _html_escape
from io import BytesIO
from pathlib import Path

try:
    from PIL import Image
except ImportError:  # pragma: no cover - only used when Pillow is unavailable.
    Image = None

TOTAL_TASKS = 89
AGENT_LOGO_EMBED_SIZE_PX = 32
DEFAULT_RUNS = 5       # Baseline run count — hidden on bars; only deviations shown
DEFAULT_TIMEOUT_H = 1  # Baseline timeout in hours — hidden on bars; only deviations shown
DEFAULT_VERSIONS = {   # Baseline agent versions — hidden on bars; only deviations shown
    "terminus-2": "2.0.0",
}

AGENT_LOGOS = {
    "terminus-2": """<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path fill-rule="evenodd" d="M4 4.5a2 2 0 0 0-2 2v11a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-11a2 2 0 0 0-2-2H4Zm0 3h16v10H4v-10Zm3.2 2.1-1 1.1 2 1.8-2 1.8 1 1.1 3.3-2.9-3.3-2.9Zm4.4 4.5v1.5h5.5v-1.5h-5.5Z"/></svg>""",
    "claude-code": """<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="m4.7144 15.9555 4.7174-2.6471.079-.2307-.079-.1275h-.2307l-.7893-.0486-2.6956-.0729-2.3375-.0971-2.2646-.1214-.5707-.1215-.5343-.7042.0546-.3522.4797-.3218.686.0608 1.5179.1032 2.2767.1578 1.6514.0972 2.4468.255h.3886l.0546-.1579-.1336-.0971-.1032-.0972L6.973 9.8356l-2.55-1.6879-1.3356-.9714-.7225-.4918-.3643-.4614-.1578-1.0078.6557-.7225.8803.0607.2246.0607.8925.686 1.9064 1.4754 2.4893 1.8336.3643.3035.1457-.1032.0182-.0728-.164-.2733-1.3539-2.4467-1.445-2.4893-.6435-1.032-.17-.6194c-.0607-.255-.1032-.4674-.1032-.7285L6.287.1335 6.6997 0l.9957.1336.419.3642.6192 1.4147 1.0018 2.2282 1.5543 3.0296.4553.8985.2429.8318.091.255h.1579v-.1457l.1275-1.706.2368-2.0947.2307-2.6957.0789-.7589.3764-.9107.7468-.4918.5828.2793.4797.686-.0668.4433-.2853 1.8517-.5586 2.9021-.3643 1.9429h.2125l.2429-.2429.9835-1.3053 1.6514-2.0643.7286-.8196.85-.9046.5464-.4311h1.0321l.759 1.1293-.34 1.1657-1.0625 1.3478-.8804 1.1414-1.2628 1.7-.7893 1.36.0729.1093.1882-.0183 2.8535-.607 1.5421-.2794 1.8396-.3157.8318.3886.091.3946-.3278.8075-1.967.4857-2.3072.4614-3.4364.8136-.0425.0304.0486.0607 1.5482.1457.6618.0364h1.621l3.0175.2247.7892.522.4736.6376-.079.4857-1.2142.6193-1.6393-.3886-3.825-.9107-1.3113-.3279h-.1822v.1093l1.0929 1.0686 2.0035 1.8092 2.5075 2.3314.1275.5768-.3218.4554-.34-.0486-2.2039-1.6575-.85-.7468-1.9246-1.621h-.1275v.17l.4432.6496 2.3436 3.5214.1214 1.0807-.17.3521-.6071.2125-.6679-.1214-1.3721-1.9246L14.38 17.959l-1.1414-1.9428-.1397.079-.674 7.2552-.3156.3703-.7286.2793-.6071-.4614-.3218-.7468.3218-1.4753.3886-1.9246.3157-1.53.2853-1.9004.17-.6314-.0121-.0425-.1397.0182-1.4328 1.9672-2.1796 2.9446-1.7243 1.8456-.4128.164-.7164-.3704.0667-.6618.4008-.5889 2.386-3.0357 1.4389-1.882.929-1.0868-.0062-.1579h-.0546l-6.3385 4.1164-1.1293.1457-.4857-.4554.0608-.7467.2307-.2429 1.9064-1.3114Z"/></svg>""",
    "hermes": """<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M13.1 1.7 5.9 13h4.5l-1.5 9.3 9.3-12.4h-5.1l2.1-8.2h-2.1Z"/><path d="M2 7.1c3.9-.4 6.4.4 8.1 2.4l-1 1.6C7.4 9.9 5.4 9.3 2 9.6V7.1Zm20 0c-3.2-.3-5.6.2-7.3 1.5l-.6 2.4c1.7-1.2 3.9-1.7 7.9-1.4V7.1Z"/></svg>""",
    "openclaw": """<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M6.1 6.4 1.8 12l4.3 5.6 2-1.5L5 12l3.1-4.1-2-1.5Zm11.8 0-2 1.5L19 12l-3.1 4.1 2 1.5 4.3-5.6-4.3-5.6ZM11 20.2 14.5 3.8h-2.4L8.6 20.2H11Z"/></svg>""",
    "cline-cli": """<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="m23.365 13.556-1.442-2.895V8.994c0-2.764-2.218-5.002-4.954-5.002h-2.464c.178-.367.276-.779.276-1.213A2.77 2.77 0 0 0 12.018 0a2.77 2.77 0 0 0-2.763 2.779c0 .434.098.846.276 1.213H7.067c-2.736 0-4.954 2.238-4.954 5.002v1.667L.64 13.549c-.149.29-.149.636 0 .927l1.472 2.855v1.667C2.113 21.762 4.33 24 7.067 24h9.902c2.736 0 4.954-2.238 4.954-5.002V17.33l1.44-2.865c.143-.286.143-.622.002-.91m-12.854 2.36a2.27 2.27 0 0 1-2.261 2.273 2.27 2.27 0 0 1-2.261-2.273v-4.042A2.27 2.27 0 0 1 8.249 9.6a2.267 2.267 0 0 1 2.262 2.274zm7.285 0a2.27 2.27 0 0 1-2.26 2.273 2.27 2.27 0 0 1-2.262-2.273v-4.042A2.267 2.267 0 0 1 15.535 9.6a2.267 2.267 0 0 1 2.261 2.274z"/></svg>""",
    "cursor-cli": """<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M11.503.131 1.891 5.678a.84.84 0 0 0-.42.726v11.188c0 .3.162.575.42.724l9.609 5.55a1 1 0 0 0 .998 0l9.61-5.55a.84.84 0 0 0 .42-.724V6.404a.84.84 0 0 0-.42-.726L12.497.131a1.01 1.01 0 0 0-.996 0M2.657 6.338h18.55c.263 0 .43.287.297.515L12.23 22.918c-.062.107-.229.064-.229-.06V12.335a.59.59 0 0 0-.295-.51l-9.11-5.257c-.109-.063-.064-.23.061-.23"/></svg>""",
    "codex": """<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M22.2819 9.8211a5.9847 5.9847 0 0 0-.5157-4.9108 6.0462 6.0462 0 0 0-6.5098-2.9A6.0651 6.0651 0 0 0 4.9807 4.1818a5.9847 5.9847 0 0 0-3.9977 2.9 6.0462 6.0462 0 0 0 .7427 7.0966 5.98 5.98 0 0 0 .511 4.9107 6.051 6.051 0 0 0 6.5146 2.9001A5.9847 5.9847 0 0 0 13.2599 24a6.0557 6.0557 0 0 0 5.7718-4.2058 5.9894 5.9894 0 0 0 3.9977-2.9001 6.0557 6.0557 0 0 0-.7475-7.0729Zm-9.022 12.6081a4.4755 4.4755 0 0 1-2.8764-1.0408l.1419-.0804 4.7783-2.7582a.7948.7948 0 0 0 .3927-.6813v-6.7369l2.02 1.1686a.071.071 0 0 1 .038.052v5.5826a4.504 4.504 0 0 1-4.4945 4.4944Zm-9.6607-4.1254a4.4708 4.4708 0 0 1-.5346-3.0137l.142.0852 4.783 2.7582a.7712.7712 0 0 0 .7806 0l5.8428-3.3685v2.3324a.0804.0804 0 0 1-.0332.0615L9.74 19.9502a4.4992 4.4992 0 0 1-6.1408-1.6464ZM2.3408 7.8956a4.485 4.485 0 0 1 2.3655-1.9728V11.6a.7664.7664 0 0 0 .3879.6765l5.8144 3.3543-2.0201 1.1685a.0757.0757 0 0 1-.071 0l-4.8303-2.7865A4.504 4.504 0 0 1 2.3408 7.872Zm16.5963 3.8558L13.1038 8.364 15.1192 7.2a.0757.0757 0 0 1 .071 0l4.8303 2.7913a4.4944 4.4944 0 0 1-.6765 8.1042v-5.6772a.79.79 0 0 0-.407-.667Zm2.0107-3.0231-.142-.0852-4.7735-2.7818a.7759.7759 0 0 0-.7854 0L9.409 9.2297V6.8974a.0662.0662 0 0 1 .0284-.0615l4.8303-2.7866a4.4992 4.4992 0 0 1 6.6802 4.66ZM8.3065 12.863l-2.02-1.1638a.0804.0804 0 0 1-.038-.0567V6.0742a4.4992 4.4992 0 0 1 7.3757-3.4537l-.142.0805L8.704 5.459a.7948.7948 0 0 0-.3927.6813Zm1.0976-2.3654 2.602-1.4998 2.6069 1.4998v2.9994l-2.5974 1.4997-2.6067-1.4997Z"/></svg>""",
}

AGENT_LOGO_ASSETS = {
    "terminus-2": ("agent-icons/terminus-2.png", "image/png"),
    "claude-code": ("agent-icons/claude-code.svg", "image/svg+xml"),
    "hermes": ("agent-icons/hermes.svg", "image/svg+xml"),
    "openclaw": ("agent-icons/openclaw.svg", "image/svg+xml"),
    "cline-cli": ("agent-icons/cline-cli.svg", "image/svg+xml"),
    "cursor-cli": ("agent-icons/cursor-cli.svg", "image/svg+xml"),
    "codex": ("agent-icons/codex.svg", "image/svg+xml"),
}

AGENT_LOGO_BRANDED: set[str] = {"openclaw"}
_AGENT_LOGO_ASSET_CACHE: dict[tuple[str, str], str] = {}

AGENT_CONFIG = {
    "terminus-2": {
        "label": "T2",
        "name": "Terminus-2",
        "gradient": {
            "solid":   ("linear-gradient(135deg, #0a3d1a 0%, #145a32 40%, #1e8449 70%, #27ae60 100%)",
                        "0 0 12px rgba(39,174,96,0.3)"),
            "average": ("linear-gradient(135deg, #1a7a3a 0%, #27ae60 40%, #2ecc71 70%, #58d68d 100%)",
                        "0 0 12px rgba(46,204,113,0.3)"),
            "best":    ("linear-gradient(135deg, #27ae60 0%, #58d68d 40%, #82e0aa 70%, #a9dfbf 100%)",
                        "0 0 12px rgba(88,214,141,0.3)"),
            "ceiling": ("linear-gradient(135deg, #58d68d 0%, #abebc6 40%, #d5f5e3 70%, #eafaf1 100%)",
                        "0 0 8px rgba(171,235,198,0.2)"),
        },
    },
    "claude-code": {
        "label": "CC",
        "name": "Claude Code",
        "gradient": {
            "solid":   ("linear-gradient(135deg, #5a2d00 0%, #7d3c00 40%, #b35900 70%, #e67e22 100%)",
                        "0 0 12px rgba(230,126,34,0.3)"),
            "average": ("linear-gradient(135deg, #7d3c00 0%, #e67e22 40%, #f0b27a 70%, #f5cba7 100%)",
                        "0 0 12px rgba(240,178,122,0.3)"),
            "best":    ("linear-gradient(135deg, #e67e22 0%, #f0b27a 40%, #f5cba7 70%, #fdebd0 100%)",
                        "0 0 12px rgba(245,203,167,0.3)"),
            "ceiling": ("linear-gradient(135deg, #f0b27a 0%, #fdebd0 40%, #fef5e7 70%, #fffaf2 100%)",
                        "0 0 8px rgba(253,235,208,0.2)"),
        },
    },
    "hermes": {
        "label": "HA",
        "name": "Hermes Agent",
        "gradient": {
            "solid":   ("linear-gradient(135deg, #5a4d00 0%, #7d6b00 40%, #b39700 70%, #f1c40f 100%)",
                        "0 0 12px rgba(241,196,15,0.3)"),
            "average": ("linear-gradient(135deg, #7d6b00 0%, #f1c40f 40%, #f4d03f 70%, #f7dc6f 100%)",
                        "0 0 12px rgba(244,208,63,0.3)"),
            "best":    ("linear-gradient(135deg, #f1c40f 0%, #f7dc6f 40%, #f9e79f 70%, #fcf3cf 100%)",
                        "0 0 12px rgba(247,220,111,0.3)"),
            "ceiling": ("linear-gradient(135deg, #f7dc6f 0%, #fcf3cf 40%, #fef9e7 70%, #fffdf2 100%)",
                        "0 0 8px rgba(252,243,207,0.2)"),
        },
    },
    "openclaw": {
        "label": "OC",
        "name": "OpenClaw",
        "gradient": {
            "solid":   ("linear-gradient(135deg, #641e16 0%, #922b21 40%, #c0392b 70%, #e74c3c 100%)",
                        "0 0 12px rgba(231,76,60,0.3)"),
            "average": ("linear-gradient(135deg, #922b21 0%, #e74c3c 40%, #ec7063 70%, #f1948a 100%)",
                        "0 0 12px rgba(241,148,138,0.3)"),
            "best":    ("linear-gradient(135deg, #e74c3c 0%, #f1948a 40%, #f5b7b1 70%, #fadbd8 100%)",
                        "0 0 12px rgba(245,183,177,0.3)"),
            "ceiling": ("linear-gradient(135deg, #f1948a 0%, #fadbd8 40%, #fdedec 70%, #fef9f8 100%)",
                        "0 0 8px rgba(250,219,216,0.2)"),
        },
    },
    "cline-cli": {
        "label": "Cl",
        "name": "Cline CLI",
        "gradient": {
            "solid":   ("linear-gradient(135deg, #2d1054 0%, #4a1a8a 40%, #6c3483 70%, #8e44ad 100%)",
                        "0 0 12px rgba(142,68,173,0.3)"),
            "average": ("linear-gradient(135deg, #4a1a8a 0%, #8e44ad 40%, #a569bd 70%, #bb8fce 100%)",
                        "0 0 12px rgba(165,105,189,0.3)"),
            "best":    ("linear-gradient(135deg, #8e44ad 0%, #bb8fce 40%, #d2b4de 70%, #e8daef 100%)",
                        "0 0 12px rgba(210,180,222,0.3)"),
            "ceiling": ("linear-gradient(135deg, #bb8fce 0%, #e8daef 40%, #f4ecf7 70%, #faf5fc 100%)",
                        "0 0 8px rgba(232,218,239,0.2)"),
        },
    },
    "cursor-cli": {
        "label": "CA",
        "name": "Cursor",
        "gradient": {
            "solid":   ("linear-gradient(135deg, #0e3855 0%, #1a5276 40%, #2874a6 70%, #3498db 100%)",
                        "0 0 12px rgba(52,152,219,0.3)"),
            "average": ("linear-gradient(135deg, #1a5276 0%, #3498db 40%, #5dade2 70%, #85c1e9 100%)",
                        "0 0 12px rgba(93,173,226,0.3)"),
            "best":    ("linear-gradient(135deg, #3498db 0%, #85c1e9 40%, #aed6f1 70%, #d6eaf8 100%)",
                        "0 0 12px rgba(133,193,233,0.3)"),
            "ceiling": ("linear-gradient(135deg, #85c1e9 0%, #d6eaf8 40%, #eaf5fb 70%, #f4fafd 100%)",
                        "0 0 8px rgba(214,234,248,0.2)"),
        },
    },
    "codex": {
        "label": "CX",
        "name": "Codex",
        "gradient": {
            "solid":   ("linear-gradient(135deg, #1e1b4b 0%, #3730a3 40%, #4f46e5 70%, #6366f1 100%)",
                        "0 0 12px rgba(99,102,241,0.3)"),
            "average": ("linear-gradient(135deg, #3730a3 0%, #6366f1 40%, #818cf8 70%, #a5b4fc 100%)",
                        "0 0 12px rgba(129,140,248,0.3)"),
            "best":    ("linear-gradient(135deg, #6366f1 0%, #a5b4fc 40%, #c7d2fe 70%, #e0e7ff 100%)",
                        "0 0 12px rgba(165,180,252,0.3)"),
            "ceiling": ("linear-gradient(135deg, #a5b4fc 0%, #e0e7ff 40%, #eef2ff 70%, #f5f7ff 100%)",
                        "0 0 8px rgba(224,231,255,0.2)"),
        },
    },
}


def _raster_logo_data_uri(logo_path: Path, mime: str) -> str:
    if Image is None:
        raise RuntimeError("Pillow is required to normalize raster agent logos.")

    with Image.open(logo_path) as source:
        image = source.convert("RGBA")

    alpha_bbox = image.getchannel("A").getbbox()
    if alpha_bbox:
        image = image.crop(alpha_bbox)

    resampling = getattr(getattr(Image, "Resampling", Image), "LANCZOS")
    image.thumbnail((AGENT_LOGO_EMBED_SIZE_PX, AGENT_LOGO_EMBED_SIZE_PX), resampling)

    canvas = Image.new("RGBA", (AGENT_LOGO_EMBED_SIZE_PX, AGENT_LOGO_EMBED_SIZE_PX), (0, 0, 0, 0))
    offset = (
        (AGENT_LOGO_EMBED_SIZE_PX - image.width) // 2,
        (AGENT_LOGO_EMBED_SIZE_PX - image.height) // 2,
    )
    canvas.alpha_composite(image, offset)

    buffer = BytesIO()
    canvas.save(buffer, format="PNG", optimize=True)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _strip_svg_tooltip_nodes(svg: str) -> str:
    return re.sub(r"<(?:title|desc)\b[^>]*>.*?</(?:title|desc)>", "", svg, flags=re.IGNORECASE | re.DOTALL)


def _agent_logo_html(agent: str, title: str) -> str:
    safe_title = _html_escape(title)
    if agent in AGENT_LOGO_ASSETS:
        cache_key = (agent, title)
        cached_logo = _AGENT_LOGO_ASSET_CACHE.get(cache_key)
        if cached_logo is not None:
            return cached_logo
        rel_path, mime = AGENT_LOGO_ASSETS[agent]
        logo_path = Path(__file__).parent / rel_path
        if logo_path.exists():
            safe_agent = _html_escape(agent)
            logo_classes = f"agent-logo agent-logo-{safe_agent}"
            if agent in AGENT_LOGO_BRANDED:
                logo_classes += " agent-logo-branded"
            if mime == "image/svg+xml":
                svg = _strip_svg_tooltip_nodes(logo_path.read_text(encoding="utf-8").strip())
                logo = f'<span class="{logo_classes}" title="{safe_title}" aria-hidden="true">{svg}</span>'
            else:
                data_uri = _raster_logo_data_uri(logo_path, mime)
                logo = (
                    f'<span class="{logo_classes}" title="{safe_title}" aria-hidden="true">'
                    f'<img src="{data_uri}" alt="" decoding="async">'
                    f'</span>'
                )
            _AGENT_LOGO_ASSET_CACHE[cache_key] = logo
            return logo

    logo = AGENT_LOGOS.get(agent)
    if not logo:
        return f'<span class="agent-logo agent-logo-missing" title="{safe_title}" aria-hidden="true"></span>'
    svg = _strip_svg_tooltip_nodes(logo)
    return f'<span class="agent-logo agent-logo-{_html_escape(agent)}" title="{safe_title}" aria-hidden="true">{svg}</span>'


def _agent_badge_html(agent: str, name: str) -> str:
    safe_name = _html_escape(name)
    return (
        f'<span class="agent-badge" title="{safe_name}" aria-label="{safe_name}">'
        f'{_agent_logo_html(agent, name)}</span>'
    )


_HEX_RE = re.compile(r"#[0-9a-fA-F]{6}")


def _blend_hex(a: str, b: str, amount: float) -> str:
    """Blend two #rrggbb colors."""
    a = a.lstrip("#")
    b = b.lstrip("#")
    ar, ag, ab = (int(a[i:i + 2], 16) for i in (0, 2, 4))
    br, bg, bb = (int(b[i:i + 2], 16) for i in (0, 2, 4))
    mix = lambda x, y: round(x * (1 - amount) + y * amount)
    return f"#{mix(ar, br):02x}{mix(ag, bg):02x}{mix(ab, bb):02x}"


def _worst_gradient(grads: dict[str, tuple[str, str]]) -> tuple[str, str]:
    """Create a visible Worst-of segment style between Solid and Average."""
    solid_grad, _ = grads["solid"]
    avg_grad, avg_shadow = grads["average"]
    solid_colors = _HEX_RE.findall(solid_grad)
    avg_colors = _HEX_RE.findall(avg_grad)
    if not solid_colors or len(solid_colors) != len(avg_colors):
        return avg_grad, avg_shadow
    stops = [0, 40, 70, 100]
    blended = [
        f"{_blend_hex(s, a, 0.55)} {stops[i] if i < len(stops) else round(i / max(1, len(solid_colors) - 1) * 100)}%"
        for i, (s, a) in enumerate(zip(solid_colors, avg_colors))
    ]
    return "linear-gradient(135deg, " + ", ".join(blended) + ")", avg_shadow


MODEL_DISPLAY = {
    "claude-opus-4-6":   "Claude Opus 4.6",
    "claude-sonnet-4-6": "Claude Sonnet 4.6",
    "Kimi-K2.5":         "Kimi K2.5",
    "MiniMax-M2.5":      "MiniMax M2.5",
    "GLM-5-FP8":         "GLM-5 FP8",
}


def _resolve_display_name(r: dict) -> str:
    """Return display name: model_display override if set, else auto-derive from model path."""
    md = r.get("model_display") or ""
    if md:
        return md
    model_full = r.get("model", "unknown")
    parts = model_full.split("/")
    if len(parts) >= 3:
        return "/".join(parts[2:])
    elif len(parts) == 2:
        return parts[-1]
    return model_full


def _normalize_thinking(t) -> str:
    """Normalize thinking/reasoning_effort to a display string."""
    if t is None:
        return "-"
    if t is True or t == "enabled":
        return "on"
    if t is False or t == "disabled":
        return "off"
    return str(t)


def _resolve_thinking(r: dict) -> str:
    """Return thinking display: thinking_display override if set, else auto-normalize."""
    td = r.get("thinking_display") or ""
    if td:
        return td
    return _normalize_thinking(r.get("thinking"))


def _resolve_version(r: dict) -> str:
    """Return agent version: version_display override if set, else agent_version."""
    vd = r.get("version_display") or ""
    if vd:
        return vd
    return r.get("agent_version") or "-"


def _resolve_provider_vendor(r: dict) -> tuple[str, str]:
    """Return (provider, vendor): overrides if set, else split from model path."""
    model_full = r.get("model", "unknown")
    parts = model_full.split("/")
    if len(parts) >= 3:
        provider = parts[0]
        vendor = parts[1]
    elif len(parts) == 2:
        provider = parts[0]
        vendor = parts[0]
    else:
        provider = "-"
        vendor = "-"
    pd = r.get("provider_display") or ""
    vd = r.get("vendor_display") or ""
    return (pd or provider, vd or vendor)


def _positive_cost_usd(value) -> float | None:
    try:
        cost = float(value)
    except (TypeError, ValueError):
        return None
    return cost if cost > 0 else None


def _fmt_cost_usd(value) -> str:
    cost = _positive_cost_usd(value)
    return f"${cost:,.2f}" if cost is not None else "-"


METRIC_LABELS = {
    "ceiling": ("★", "Ceiling",  "ever solved"),
    "best":    ("▲", "Best-of",  "peak run"),
    "average": ("∅", "Average",  "mean score"),
    "worst":   ("▼", "Worst-of", "lowest run"),
    "solid":   ("■", "Solid",    "always solved"),
}


def compute_metrics(runs: list[dict]) -> dict | None:
    n_runs = len(runs)
    scores = [r["score"] for r in runs if r["score"] is not None]
    if not scores:
        return None

    task_pass_counts = Counter()
    for r in runs:
        for t in r["passed_tasks"]:
            task_pass_counts[t] += 1

    solid = sum(1 for c in task_pass_counts.values() if c == n_runs)
    ceiling = len(task_pass_counts)

    # Extract timeout (most common value; typically uniform per group)
    timeouts = [r.get("timeout_sec") for r in runs if r.get("timeout_sec") is not None]
    timeout_sec = max(set(timeouts), key=timeouts.count) if timeouts else None

    token_input_total = 0
    token_output_total = 0
    cost_total = 0.0
    cost_runs = 0
    for r in runs:
        token_input_total += (r.get("tokens_in") or 0) + (r.get("tokens_cache_write") or 0)
        token_output_total += r.get("tokens_out") or 0
        cost = _positive_cost_usd(r.get("cost_usd"))
        if cost is not None:
            cost_total += cost
            cost_runs += 1

    avg_score = sum(scores) / len(scores)
    return {
        "n_runs": n_runs,
        "min": round(min(scores) * 100),
        "solid": round(solid / TOTAL_TASKS * 100),
        "average": round(avg_score * 100),
        "best": round(max(scores) * 100),
        "ceiling": round(ceiling / TOTAL_TASKS * 100),
        "min_abs": round(min(scores) * TOTAL_TASKS),
        "solid_abs": solid,
        "avg_abs": round(avg_score * TOTAL_TASKS),
        "best_abs": round(max(scores) * TOTAL_TASKS),
        "ceiling_abs": ceiling,
        # Raw unrounded values (0-TOTAL_TASKS range) for tiebreak comparisons —
        # avoid rounding artifacts like 63 vs 64 both displaying as 71%.
        "min_raw": min(scores) * TOTAL_TASKS,
        "solid_raw": float(solid),
        "avg_raw": avg_score * TOTAL_TASKS,
        "best_raw": max(scores) * TOTAL_TASKS,
        "ceiling_raw": float(ceiling),
        "timeout_sec": timeout_sec,
        "tokens_in_total": token_input_total,
        "tokens_out_total": token_output_total,
        "tokens_total": token_input_total + token_output_total,
        "tokens_runs": n_runs,
        "cost_total_usd": cost_total,
        "cost_runs": cost_runs,
    }


def _fmt_timeout_h(sec: float | int | None) -> str:
    """Convert timeout seconds to compact hours string: 7200→'2h', 5400→'1.5h'."""
    if sec is None:
        return ""
    h = sec / 3600
    return f"{h:.0f}h" if h == int(h) else f"{h:.1f}h"


def _parse_run_datetime(value: str | None) -> datetime | None:
    """Parse ISO datetimes or Harbor run-dir timestamps."""
    if not value:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    normalized = raw.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is not None:
            return parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return parsed
    except ValueError:
        pass
    match = re.match(r"^(\d{4}-\d{2}-\d{2})__(\d{2})-(\d{2})(?:-(\d{2}))?", raw)
    if not match:
        return None
    date_part, hh, mm, ss = match.groups()
    try:
        return datetime.fromisoformat(f"{date_part}T{hh}:{mm}:{ss or '00'}")
    except ValueError:
        return None


def _run_datetime_label_and_sort(run: dict) -> tuple[str, str]:
    dt = _parse_run_datetime(run.get("started_at")) or _parse_run_datetime(run.get("timestamp"))
    if dt is None:
        ts = str(run.get("timestamp") or "").strip()
        return (ts[:10] if ts else "-", "")
    return dt.strftime("%Y-%m-%d %H:%M"), str(int(dt.timestamp()))


# Scale: pixels per percentage point
PX_PER_PCT = 6
CHART_HEIGHT = 100 * PX_PER_PCT  # 600px for 100%


def _bar_segments_html(metrics: dict, agent_cfg: dict) -> str:
    """Generate the stacked bar segments for one agent/model combo."""
    grads = agent_cfg["gradient"]
    _abs_px = lambda v: v / TOTAL_TASKS * 100 * PX_PER_PCT

    seg = [
        ("solid",   metrics["solid"],                       metrics["solid_abs"]),
        ("worst",   metrics["min"] - metrics["solid"],      metrics["min_abs"] - metrics["solid_abs"]),
        ("average", metrics["average"] - metrics["min"],    metrics["avg_abs"] - metrics["min_abs"]),
        ("best",    metrics["best"] - metrics["average"],   metrics["best_abs"] - metrics["avg_abs"]),
        ("ceiling", metrics["ceiling"] - metrics["best"],   metrics["ceiling_abs"] - metrics["best_abs"]),
    ]

    # Segment divs (no labels inside — labels are positioned separately)
    parts = []
    for key, height_pct, height_abs in seg:
        if height_pct <= 0 and height_abs <= 0:
            continue
        gradient, shadow = _worst_gradient(grads) if key == "worst" else grads[key]
        px_h = max(height_pct * PX_PER_PCT, 2)
        px_h_abs = max(_abs_px(height_abs), 2)
        parts.append(f'''
            <div class="segment segment-{key}" data-metric="{key}"
                 data-h-pct="{px_h:.1f}" data-h-abs="{px_h_abs:.1f}" style="
                height: {px_h}px;
                background: {gradient};
                box-shadow: {shadow}, inset 0 1px 0 rgba(255,255,255,0.15), inset 0 -1px 0 rgba(0,0,0,0.2);
            ">
                <div class="segment-shine"></div>
            </div>''')

    # Reverse so ceiling is on top (we build bottom-up)
    parts.reverse()

    # Collect labels, then nudge to avoid overlap
    total_h = metrics["ceiling"] * PX_PER_PCT
    total_h_abs = _abs_px(metrics["ceiling_abs"])

    if metrics["n_runs"] == 1:
        # Single run: all five metrics are identical — just show the value, no symbols
        val = metrics["ceiling"]
        abs_val = metrics["ceiling_abs"]
        bottom_px = val * PX_PER_PCT
        abs_bottom_px = _abs_px(abs_val)
        label_parts = [
            f'<span class="seg-label seg-label-single" data-metric="solid"'
            f' data-true-bottom="{bottom_px:.1f}"'
            f' data-bottom-pct="{bottom_px:.1f}" data-bottom-abs="{abs_bottom_px:.1f}"'
            f' style="bottom: {bottom_px:.1f}px;">'
            f'<span class="seg-pct" data-pct="{val}%" data-abs="{abs_val}">{val}%</span></span>'
        ]
    else:
        _val_key = {"worst": "min", "solid": "solid", "average": "average",
                    "best": "best", "ceiling": "ceiling"}
        _abs_key = {"worst": "min_abs", "solid": "solid_abs", "average": "avg_abs",
                    "best": "best_abs", "ceiling": "ceiling_abs"}
        labels = []
        for key in ("worst", "solid", "average", "best", "ceiling"):
            val = metrics[_val_key[key]]
            abs_val = metrics[_abs_key[key]]
            sym, name, _ = METRIC_LABELS[key]
            labels.append((val, abs_val, sym, f"{val}%", str(abs_val), key))

        labels.sort(key=lambda t: t[0])

        # Collision avoidance helper
        def _snap_positions(raw_px: list[float], max_bottom: float) -> list[float]:
            min_gap_px = 15  # ~label height at 0.7rem
            positions = list(raw_px)
            for _ in range(40):
                changed = False
                for i in range(len(positions) - 1):
                    gap = positions[i + 1] - positions[i]
                    if gap < min_gap_px:
                        push = (min_gap_px - gap) / 2
                        positions[i] -= push
                        positions[i + 1] += push
                        changed = True
                if positions and positions[-1] > max_bottom:
                    overshoot = positions[-1] - max_bottom
                    positions = [p - overshoot for p in positions]
                    changed = True
                if positions and positions[0] < 0:
                    undershoot = -positions[0]
                    positions = [p + undershoot for p in positions]
                    changed = True
                if not changed:
                    break
            return positions

        # Compute positions for both percentage and absolute modes
        pct_raw = [val * PX_PER_PCT for val, _, _, _, _, _ in labels]
        abs_raw = [abs_v / TOTAL_TASKS * 100 * PX_PER_PCT for _, abs_v, _, _, _, _ in labels]
        pct_positions = _snap_positions(pct_raw, total_h)
        abs_positions = _snap_positions(abs_raw, total_h)

        label_parts = []
        for (val, abs_v, sym, pct, abs_val, metric_key), bottom_px, abs_bottom_px in zip(
                labels, pct_positions, abs_positions):
            true_px = val * PX_PER_PCT
            label_parts.append(
                f'<span class="seg-label" data-metric="{metric_key}"'
                f' data-true-bottom="{true_px:.1f}"'
                f' data-bottom-pct="{bottom_px:.1f}" data-bottom-abs="{abs_bottom_px:.1f}"'
                f' style="bottom: {bottom_px:.1f}px;">'
                f'<span class="seg-sym">{sym}</span>'
                f'<span class="seg-pct" data-pct="{pct}" data-abs="{abs_val}">{pct}</span></span>'
            )

    segments_html = "\n".join(parts)
    labels_html = "\n".join(label_parts)

    worst_px = metrics["min"] * PX_PER_PCT

    return f'''
        <div class="bar-inner" style="height: {total_h}px;"
             data-h-pct="{total_h:.1f}" data-h-abs="{total_h_abs:.1f}"
             data-h-worst="{worst_px:.1f}"
             data-h-solid="{metrics['solid'] * PX_PER_PCT:.1f}"
             data-h-average="{metrics['average'] * PX_PER_PCT:.1f}"
             data-h-best="{metrics['best'] * PX_PER_PCT:.1f}"
             data-h-ceiling="{total_h:.1f}">
            <div class="bar-segments">{segments_html}</div>
            <div class="bar-labels">{labels_html}</div>
        </div>'''


def _build_runs_table_html(
    runs: list[dict],
    weave_run_urls: dict[tuple, str] | None = None,
) -> str:
    """Build a collapsed HTML <details> table showing individual run data."""
    if not runs:
        return ""

    def _fmt_tok(n):
        if not n:
            return "-"
        if n >= 1_000_000_000:
            return f"{n / 1_000_000_000:.2f}".rstrip("0").rstrip(".") + "B"
        if n >= 1_000_000:
            return f"{n / 1_000_000:.1f}M"
        if n >= 1_000:
            return f"{n / 1_000:.0f}K"
        return str(n)

    def _safe_float(value) -> float:
        try:
            f = float(value or 0)
        except (TypeError, ValueError):
            return 0.0
        return f if f > 0 else 0.0

    def _fmt_duration_total(seconds: float) -> str:
        total = int(round(seconds))
        if total <= 0:
            return "n/a"
        days, rem = divmod(total, 86_400)
        hours, rem = divmod(rem, 3_600)
        minutes, _ = divmod(rem, 60)
        parts = []
        if days:
            parts.append(f"{days}d")
        if hours or days:
            parts.append(f"{hours}h")
        parts.append(f"{minutes}m")
        return " ".join(parts)

    def _build_resource_stats_text(visible_runs: list[dict]) -> str:
        n_visible = len(visible_runs)
        duration_total = 0.0
        duration_runs = 0
        token_in_total = 0
        token_out_total = 0
        token_runs = 0
        cost_total = 0.0
        cost_runs = 0

        for _r in visible_runs:
            _duration = _safe_float(_r.get("duration_sec"))
            if _duration:
                duration_total += _duration
                duration_runs += 1

            _tok_in = (_r.get("tokens_in") or 0) + (_r.get("tokens_cache_write") or 0)
            _tok_out = _r.get("tokens_out") or 0
            _tok_total = _tok_in + _tok_out
            if _tok_total:
                token_in_total += _tok_in
                token_out_total += _tok_out
                token_runs += 1

            _cost = _positive_cost_usd(_r.get("cost_usd"))
            if _cost is not None:
                cost_total += _cost
                cost_runs += 1

        duration_label = _fmt_duration_total(duration_total)
        if duration_runs and duration_runs != n_visible:
            duration_label += f" (timing data for {duration_runs}/{n_visible} runs)"

        token_total = token_in_total + token_out_total
        if token_total:
            token_label = f"{_fmt_tok(token_total)} ({_fmt_tok(token_in_total)} in, {_fmt_tok(token_out_total)} out)"
            if token_runs != n_visible:
                token_label += f" (token data for {token_runs}/{n_visible} runs)"
        else:
            token_label = "n/a"

        if cost_runs:
            cost_label = _fmt_cost_usd(cost_total)
            if cost_runs != n_visible:
                cost_label += f" (cost data for {cost_runs}/{n_visible} runs)"
        else:
            cost_label = "n/a"

        return (
            f"Total runtime: {duration_label} · "
            f"Total tokens: {token_label} · "
            f"Total cost: {cost_label}."
        )

    # Sort: date descending (latest first)
    sorted_runs = sorted(
        runs,
        key=lambda r: _parse_run_datetime(r.get("started_at")) or _parse_run_datetime(r.get("timestamp")) or datetime.min,
        reverse=True,
    )

    rows: list[str] = []
    for r in sorted_runs:
        ts = r.get("timestamp", "")
        date_time, date_sort_value = _run_datetime_label_and_sort(r)

        # Agent (full name) + version in brackets: "OpenClaw (v2026.2.17)"
        agent = r.get("agent", "?")
        agent_name = AGENT_CONFIG.get(agent, {}).get("name", agent)
        ver = _resolve_version(r)
        agent_ver = f"{agent_name} ({ver})" if ver != "-" else agent_name

        # Provider / Vendor (override if set, else split from full model path)
        provider, vendor = _resolve_provider_vendor(r)

        model = _resolve_display_name(r)

        think = _resolve_thinking(r)
        run_url = (weave_run_urls or {}).get(
            (agent, ver if ver != "-" else "unknown", model, r.get("timeout_sec"), think, ts)
        )
        if run_url:
            date_cell = (
                f'<a class="run-link" href="{_html_escape(run_url)}" target="_blank" '
                f'rel="noopener noreferrer" title="View this run trace on W&amp;B Weave">'
                f'{_html_escape(date_time)}</a>'
            )
        else:
            date_cell = _html_escape(date_time)

        score = f'{r["score"]:.1%}' if r.get("score") is not None else "?"
        n_p = r.get("n_passed", 0)
        n_f = r.get("n_failed", 0)
        n_t = r.get("n_trials", 0)

        to_sec = r.get("timeout_sec")
        to_str = f"{int(to_sec)}s" if to_sec is not None else "-"

        eb = r.get("error_breakdown", {})
        ato = eb.get("AgentTimeoutError", 0)
        lost = max(0, n_t - n_p - n_f)

        duration_sec = _safe_float(r.get("duration_sec"))
        dur = "-"
        if duration_sec:
            h, rem = divmod(int(duration_sec), 3600)
            m, _ = divmod(rem, 60)
            dur = f"{h}h{m:02d}m"

        # tokens_cache is a discounted subset of tokens_in, not extra input.
        tok_in_raw = r.get("tokens_in")
        tok_cache_write_raw = r.get("tokens_cache_write")
        tok_cache_raw = r.get("tokens_cache")
        tok_total_in = None
        if tok_in_raw is not None or tok_cache_write_raw is not None:
            tok_total_in = (tok_in_raw or 0) + (tok_cache_write_raw or 0)
        tok_in = _fmt_tok(tok_total_in)
        tok_out_raw = r.get("tokens_out")
        tok_out = _fmt_tok(tok_out_raw)
        tok_total_raw = (
            (tok_total_in or 0) + (tok_out_raw or 0)
            if tok_total_in is not None or tok_out_raw is not None else None
        )
        tok_total = _fmt_tok(tok_total_raw)

        cost_value = _positive_cost_usd(r.get("cost_usd"))
        cost_str = _fmt_cost_usd(cost_value)
        cost_sort_value = f"{cost_value:.6f}" if cost_value is not None else ""
        cost_attr = f"{cost_value:.6f}" if cost_value is not None else "0"

        _passed_json = json.dumps(r.get("passed_tasks", []), separators=(",", ":"))
        rows.append(
            f"<tr data-agent=\"{_html_escape(agent)}\" data-model=\"{_html_escape(model)}\" data-passed='{_passed_json}' "
            f'data-duration-sec="{duration_sec:.3f}" data-token-input="{int(tok_total_in or 0)}" '
            f'data-token-output="{int(tok_out_raw or 0)}" data-token-total="{int(tok_total_raw or 0)}" '
            f'data-cost-usd="{cost_attr}">'
            f"<td data-sort-value=\"{date_sort_value}\">{date_cell}</td>"
            f"<td>{_html_escape(agent_ver)}</td>"
            f"<td>{_html_escape(provider)}</td>"
            f"<td>{_html_escape(vendor)}</td>"
            f"<td>{_html_escape(model)}</td>"
            f"<td>{think}</td>"
            f"<td>{score}</td>"
            f"<td>{n_p}</td>"
            f"<td>{n_f}</td>"
            f"<td>{to_str}</td>"
            f"<td>{ato}</td>"
            f"<td>{lost}</td>"
            f"<td>{dur}</td>"
            f"<td>{tok_in}</td>"
            f"<td>{tok_out}</td>"
            f"<td>{tok_total}</td>"
            f"<td class='n' data-sort-value=\"{cost_sort_value}\">{cost_str}</td>"
            f"</tr>"
        )

    # Compute aggregate task stats across all runs
    _task_counts = Counter()
    for _r in runs:
        for _t in _r.get("passed_tasks", []):
            _task_counts[_t] += 1
    _n_total_runs = len(runs)
    _solved_once = len(_task_counts)
    _solved_always = sum(1 for _c in _task_counts.values() if _c == _n_total_runs) if _n_total_runs > 0 else 0
    _never_solved = TOTAL_TASKS - _solved_once
    _pct = lambda x: round(x / TOTAL_TASKS * 100)
    _task_stats_html = (
        f'<p class="task-stats" id="taskStats" data-total-tasks="{TOTAL_TASKS}">Across these {_n_total_runs} runs, '
        f'{_solved_once} ({_pct(_solved_once)}%) of the {TOTAL_TASKS} tasks were solved at least once, '
        f'{_solved_always} ({_pct(_solved_always)}%) were solved every time, '
        f'and {_never_solved} ({_pct(_never_solved)}%) were never solved.</p>'
    )
    _resource_stats_html = (
        f'<p class="task-stats run-resource-stats" id="runResourceStats">'
        f'{_html_escape(_build_resource_stats_text(runs))}</p>'
    )

    return (
        f'<details class="runs-details">\n'
        f'<summary>Run Details ({len(runs)} runs)</summary>\n'
        f'{_task_stats_html}\n'
        f'{_resource_stats_html}\n'
        f'<div class="runs-table-wrap">\n'
        f'<table class="runs-table">\n'
        f'<thead><tr>'
        f'<th data-sort="desc">Date</th><th>Agent</th>'
        f'<th>Provider</th><th>Vendor</th><th>Model</th><th>Think</th>'
        f'<th>Score</th><th>Pass</th><th>Fail</th>'
        f'<th>Timeout</th><th>Timeouts</th><th>Err</th>'
        f'<th>Duration</th>'
        f'<th>In</th><th>Out</th><th>Total</th>'
        f'<th>Cost</th>'
        f'</tr></thead>\n'
        f'<tbody>\n{"".join(rows)}\n</tbody>\n'
        f'</table>\n'
        f'</div>\n'
        f'</details>'
    )


def generate_html(
    groups: dict[tuple[str, str, str, float | None, str], dict],
    output_path: Path,
    min_runs: int = 1,
    agent_versions: dict[str, set[str]] | None = None,
    chart_date: str | None = None,
    runs: list[dict] | None = None,
    weave_urls: dict[tuple, str] | None = None,
    weave_run_urls: dict[tuple, str] | None = None,
) -> Path:
    # Embed logos as base64 so the generated HTML stays standalone.
    _asset_dir = Path(__file__).parent
    _wolfbench_logo_path = _asset_dir / "WolfBench-Logo-256.png"
    _wandb_cw_logo_path = _asset_dir / "Endorsed_secondary_goldwhite.png"
    wolfbench_logo_b64 = base64.b64encode(_wolfbench_logo_path.read_bytes()).decode("ascii")
    wandb_cw_logo_b64 = base64.b64encode(_wandb_cw_logo_path.read_bytes()).decode("ascii")
    three_bars_js = (Path(__file__).parent / "wolfbench-threejs-bars.js").read_text()

    # Filter
    groups = {k: v for k, v in groups.items() if v["n_runs"] >= min_runs}
    if not groups:
        print("No groups meet the minimum run threshold.")
        return None

    # Organize by model — keyed by (agent, version, timeout, thinking) tuple
    models_with_data: dict[str, dict[tuple[str, str, float | None, str], dict]] = defaultdict(dict)
    for (agent, ver, model, timeout, thinking), metrics in groups.items():
        models_with_data[model][(agent, ver, timeout, thinking)] = metrics

    # Tiebreaker cascade within each agent: primary metric (avg) first,
    # then others in legend-display order. Missing agent ranks last.
    # Uses RAW (unrounded) values to avoid rounding artifacts in ties.
    _TIEBREAK_METRICS = ("avg_raw", "ceiling_raw", "best_raw", "min_raw", "solid_raw")

    def _model_sort_key(m: str) -> tuple[float, ...]:
        key: list[float] = []
        for a in AGENT_CONFIG:
            agent_data = [v for (ag, *_), v in models_with_data[m].items() if ag == a]
            for data_key in _TIEBREAK_METRICS:
                if agent_data:
                    key.append(-max(v[data_key] for v in agent_data))
                else:
                    key.append(1)  # missing agent ranks after any real score (negated: -N..0)
        return tuple(key)

    model_order = sorted(models_with_data.keys(), key=_model_sort_key)

    # Ordered (agent, version, timeout, thinking) quads: AGENT_CONFIG order, then version/timeout/thinking asc
    _seen_quads: set[tuple[str, str, float | None, str]] = set()
    for m_data in models_with_data.values():
        _seen_quads.update(m_data.keys())
    agent_ver_order: list[tuple[str, str, float | None, str]] = []
    for a in AGENT_CONFIG:
        matches = sorted(
            ((ver, to, th) for (ag, ver, to, th) in _seen_quads if ag == a),
            key=lambda x: (x[0], x[1] or 0, x[2]),
        )
        for v, t, th in matches:
            agent_ver_order.append((a, v, t, th))
    # Flat agent list (unique, preserving AGENT_CONFIG order) for legend/footer
    agent_order = [a for a in AGENT_CONFIG
                   if any(ag == a for ag, _, _, _ in agent_ver_order)]

    # Build model groups HTML
    model_groups_html = []
    model_group_widths = []
    for _model_idx, model in enumerate(model_order):
        bars_html = []
        group_bar_widths = []
        # Per-agent per-metric scores for JS re-sorting on agent/metric filter
        _scores: dict[str, dict[str, float]] = {}
        _raw_key = {"solid": "solid_raw", "average": "avg_raw", "best": "best_raw",
                    "ceiling": "ceiling_raw", "worst": "min_raw"}
        for _a in agent_order:
            _am: dict[str, float] = {}
            for (ag, ver_, to_, th_), v in models_with_data[model].items():
                if ag == _a:
                    for _mk in ("solid", "average", "best", "ceiling"):
                        _am[_mk] = max(_am.get(_mk, 0.0), v[_mk])
                        _rk = _raw_key[_mk]
                        _am[_mk + "_raw"] = max(_am.get(_mk + "_raw", 0.0), v[_rk])
                    _am["worst"] = max(_am.get("worst", 0.0), v["min"])
                    _am["worst_raw"] = max(_am.get("worst_raw", 0.0), v["min_raw"])
            if _am:
                _scores[_a] = {k: (round(v, 4) if k.endswith("_raw") else round(v, 1))
                               for k, v in _am.items()}
        _scores_json = json.dumps(_scores, separators=(",", ":"))
        # Within each agent, sort variants by score cascade (avg → ceiling → best → worst → solid).
        # Uses raw values to avoid rounding ties. Matches JS within-agent tiebreaker.
        _ordered_quads: list[tuple[str, str, float | None, str]] = []
        for _a in AGENT_CONFIG:
            _variants = [
                (ag, ver, to, th)
                for (ag, ver, to, th) in models_with_data[model]
                if ag == _a
            ]
            _variants.sort(key=lambda q: (
                -models_with_data[model][q]["avg_raw"],
                -models_with_data[model][q]["ceiling_raw"],
                -models_with_data[model][q]["best_raw"],
                -models_with_data[model][q]["min_raw"],
                -models_with_data[model][q]["solid_raw"],
            ))
            _ordered_quads.extend(_variants)
        for agent, ver, timeout, thinking in _ordered_quads:
            m = models_with_data[model][(agent, ver, timeout, thinking)]
            cfg = AGENT_CONFIG[agent]
            segments = _bar_segments_html(m, cfg)
            n_runs = m["n_runs"]
            bar_w = 56 + 8 * max(0, min(n_runs, 10) - 5)
            group_bar_widths.append(bar_w)
            _ver_is_default = ver == "unknown" or ver == DEFAULT_VERSIONS.get(agent)
            top_label_parts = []
            if not _ver_is_default:
                top_label_parts.append(f'<span class="version-label">{ver}</span>')
            if thinking != "-":
                top_label_parts.append(f'<span class="thinking-label">\U0001f9e0 {thinking}</span>')
            top_label_html = (
                f'<div class="bar-top-label">{"<br>".join(top_label_parts)}</div>'
                if top_label_parts else ""
            )
            _wurl = (weave_urls or {}).get((agent, ver, model, m.get("timeout_sec"), thinking))
            _wopen = f'<a href="{_html_escape(_wurl)}" target="_blank" class="bar-link" title="View on W&amp;B Weave">' if _wurl else ""
            _wclose = "</a>" if _wurl else ""
            _bar_scores = {k: round(m[k], 1) for k in ("solid", "average", "best", "ceiling")}
            _bar_scores["worst"] = round(m["min"], 1)
            _bar_scores["solid_raw"] = round(m["solid_raw"], 4)
            _bar_scores["average_raw"] = round(m["avg_raw"], 4)
            _bar_scores["best_raw"] = round(m["best_raw"], 4)
            _bar_scores["ceiling_raw"] = round(m["ceiling_raw"], 4)
            _bar_scores["worst_raw"] = round(m["min_raw"], 4)
            _bar_scores_json = json.dumps(_bar_scores, separators=(",", ":"))
            _tok_in = int(round(m.get("tokens_in_total") or 0))
            _tok_out = int(round(m.get("tokens_out_total") or 0))
            _tok_total = int(round(m.get("tokens_total") or (_tok_in + _tok_out)))
            _tok_runs = int(m.get("tokens_runs") or n_runs)
            _cost_total = float(m.get("cost_total_usd") or 0)
            _cost_runs = int(m.get("cost_runs") or 0)
            _agent_version = "" if ver == "unknown" else ver
            _agent_badge = _agent_badge_html(agent, cfg["name"])
            bars_html.append(f'''
                <div class="bar-wrapper" data-agent="{agent}" data-runs="{n_runs}" data-bar-scores='{_bar_scores_json}'
                     data-agent-name="{_html_escape(cfg["name"])}" data-agent-version="{_html_escape(_agent_version)}"
                     data-token-input="{_tok_in}" data-token-output="{_tok_out}" data-token-total="{_tok_total}" data-token-runs="{_tok_runs}"
                     data-cost-total="{_cost_total:.6f}" data-cost-runs="{_cost_runs}" draggable="true">
                    {top_label_html}
                    {_wopen}<div class="bar" data-agent="{agent}" style="width: {bar_w}px;">
                        {segments}
                        <div class="bar-bottom-label">{_agent_badge}</div>
                    </div>{_wclose}
                </div>''')

        group_w = (sum(group_bar_widths) + max(0, len(group_bar_widths) - 1) * 8) if group_bar_widths else 0
        if not group_bar_widths:
            continue  # Skip models with no bars (agent not in AGENT_CONFIG)
        model_group_widths.append(group_w)

        display = MODEL_DISPLAY.get(model, model)
        model_groups_html.append(f'''
            <div class="model-group" data-model="{_html_escape(model)}" data-width="{group_w}" data-orig-order="{_model_idx}" data-scores='{_scores_json}'>
                <div class="model-highlight-box" aria-hidden="true"></div>
                <div class="model-label">{display}</div>
                <div class="bars-row">
                    {"".join(bars_html)}
                </div>
            </div>''')

    # Minimum chart width based on actual bar content
    n_groups = len(model_group_widths)
    chart_min_w = (
        sum(model_group_widths) + max(0, n_groups - 1) * 64 + 2 * 48
    ) if n_groups else 400

    # Legend
    legend_agents = []
    for agent in agent_order:
        cfg = AGENT_CONFIG[agent]
        legend_agents.append(
            f'<span class="legend-agent legend-agent-{agent}" data-agent="{agent}" draggable="true">'
            f'{_agent_badge_html(agent, cfg["name"])}<span class="legend-agent-name">{cfg["name"]}</span></span>'
        )

    legend_metrics = []
    for key in ("ceiling", "best", "average", "worst", "solid"):
        sym, name, desc = METRIC_LABELS[key]
        legend_metrics.append(
            f'<span class="legend-metric legend-metric-{key}" data-metric="{key}">'
            f'{sym} {name}&nbsp;<small>({desc})</small></span>'
        )

    # Model bar buttons (toggle visibility + drag to reorder)
    model_bar_buttons = []
    for _btn_idx, model in enumerate(model_order):
        display = MODEL_DISPLAY.get(model, model)
        _btn_scores: dict[str, dict[str, float]] = {}
        for _a in agent_order:
            _am: dict[str, float] = {}
            for (ag, ver_, to_, th_), v in models_with_data[model].items():
                if ag == _a:
                    for _mk in ("solid", "average", "best", "ceiling"):
                        _am[_mk] = max(_am.get(_mk, 0.0), v[_mk])
                    _am["worst"] = max(_am.get("worst", 0.0), v["min"])
            if _am:
                _btn_scores[_a] = {k: round(v, 1) for k, v in _am.items()}
        _btn_scores_json = json.dumps(_btn_scores, separators=(",", ":"))
        if not _btn_scores:
            continue  # Skip models with no bars
        model_bar_buttons.append(
            f'<span class="model-btn" data-model="{_html_escape(model)}" data-orig-order="{_btn_idx}" data-scores=\'{_btn_scores_json}\' draggable="true">'
            f'{display}</span>'
        )

    # Build agent version line for footer + JS lookup
    _agent_version_map: dict[str, str] = {}
    _version_parts = []
    for _a in agent_order:
        _cfg = AGENT_CONFIG[_a]
        _vers = agent_versions.get(_a, set()) if agent_versions else set()
        if _vers:
            _ver_list = ", ".join(sorted(_vers))
            _entry = f"{_cfg['name']} ({_ver_list})"
        else:
            _entry = _cfg["name"]
        _version_parts.append(_entry)
        _agent_version_map[_a] = _entry
    agent_version_line = " &middot; ".join(_version_parts)

    # ------------------------------------------------------------------
    # Metric-filter CSS — generated from AGENT_CONFIG gradients.
    # Built as a plain string, interpolated into the f-string template
    # via {metric_filter_css}.
    # ------------------------------------------------------------------
    _METRIC_ORDER = ["solid", "average", "best", "ceiling"]
    _mf_parts: list[str] = []
    for _fi, _fkey in enumerate(_METRIC_ORDER):
        # Hide segments above the selected metric level
        for _above in _METRIC_ORDER[_fi + 1:]:
            _mf_parts.append(
                f".chart-area.metric-filter-{_fkey} .segment-{_above}"
                f" {{ display: none !important; }}"
            )
        # Hide non-matching labels
        _mf_parts.append(
            f'.chart-area.metric-filter-{_fkey} .seg-label:not([data-metric="{_fkey}"])'
            f" {{ display: none !important; }}"
        )
        # Border-radius on the new topmost visible segment
        if _fkey == "solid":
            _mf_parts.append(
                ".chart-area.metric-filter-solid .segment-worst"
                " { display: none !important; }"
            )
            _mf_parts.append(
                f".chart-area.metric-filter-solid .segment-solid"
                f" {{ border-radius: 8px !important; }}"
            )
        elif _fkey != "ceiling":
            _mf_parts.append(
                f".chart-area.metric-filter-{_fkey} .segment-{_fkey}"
                f" {{ border-radius: 8px 8px 0 0 !important; }}"
            )
        # Per-agent color overrides: apply the original full-range gradient
        # to the .bar-segments container and make individual segments
        # transparent.  The container renders one seamless gradient across
        # the whole bar — no per-segment restart, full 3D look.
        for _agent, _cfg in AGENT_CONFIG.items():
            _grad, _shad = _cfg["gradient"][_fkey]
            _mf_parts.append(
                f'.chart-area.metric-filter-{_fkey} .bar[data-agent="{_agent}"]'
                f" .bar-segments {{ background: {_grad};"
                f" box-shadow: {_shad},"
                f" inset 0 1px 0 rgba(255,255,255,0.15),"
                f" inset 0 -1px 0 rgba(0,0,0,0.2); }}"
            )
    # Worst-of filter: show the solid base plus the worst segment, use solid gradient.
    for _seg in ("average", "best", "ceiling"):
        _mf_parts.append(
            f".chart-area.metric-filter-worst .segment-{_seg}"
            f" {{ display: none !important; }}"
        )
    _mf_parts.append(
        '.chart-area.metric-filter-worst .seg-label:not([data-metric="worst"])'
        " { display: none !important; }"
    )
    for _agent, _cfg in AGENT_CONFIG.items():
        _grad, _shad = _cfg["gradient"]["solid"]
        _mf_parts.append(
            f'.chart-area.metric-filter-worst .bar[data-agent="{_agent}"]'
            f" .bar-segments {{ background: {_grad};"
            f" box-shadow: {_shad},"
            f" inset 0 1px 0 rgba(255,255,255,0.15),"
            f" inset 0 -1px 0 rgba(0,0,0,0.2); }}"
        )
    # Hide single-run bars when any metric filter is active (metrics are meaningless for 1R)
    _mf_parts.append(
        '.chart-area[class*="metric-filter"] .bar-wrapper[data-runs="1"]'
        ' { display: none !important; }'
    )
    metric_filter_css = "\n".join(_mf_parts)

    # ------------------------------------------------------------------
    # Runs-table CSS — plain string, interpolated via {runs_table_css}.
    # ------------------------------------------------------------------
    runs_table_css = """
/* Run details table */
.runs-details {
    margin: 20px 0 0;
    padding: 18px 28px;
    background: rgba(26,28,31,0.8);
    border: 1px solid #2E3338;
    border-radius: 12px;
}
.runs-details summary {
    font-family: 'Source Serif 4', Georgia, serif;
    font-size: 1.3rem;
    font-weight: 700;
    color: #FFCC33;
    cursor: pointer;
    user-select: none;
    padding: 4px 0;
}
.runs-details summary:hover { opacity: 0.85; }
.task-stats {
    color: #8b949e;
    font-size: 0.85rem;
    margin: 8px 0 0;
    line-height: 1.5;
}
.run-resource-stats {
    margin-top: 0;
    margin-bottom: 12px;
}
.runs-table-wrap {
    overflow-x: auto;
    margin-top: 16px;
}
.runs-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.82rem;
    white-space: nowrap;
}
.runs-table th {
    position: sticky;
    top: 0;
    background: #22262A;
    color: #9BA1A6;
    font-weight: 600;
    text-align: left;
    padding: 8px 10px;
    border-bottom: 2px solid #2E3338;
}
.runs-table td {
    padding: 6px 10px;
    color: #c9d1d9;
    border-bottom: 1px solid rgba(46,51,56,0.6);
}
.runs-table td {
    font-variant-numeric: tabular-nums;
}
.runs-table tbody tr:nth-child(even) {
    background: rgba(46,51,56,0.25);
}
.runs-table tbody tr:hover {
    background: rgba(255,204,51,0.06);
}
.runs-table th::after {
    display: inline-block;
    width: 1em;
    margin-left: 2px;
    text-align: center;
    content: '';
    vertical-align: middle;
}
.runs-table th[data-sort='asc']::after { content: '\\25B2'; color: #FFCC33; }
.runs-table th[data-sort='desc']::after { content: '\\25BC'; color: #FFCC33; }
.runs-table a.run-link {
    color: #FFCC33;
    text-decoration: none;
    border-bottom: 1px solid rgba(255,204,51,0.35);
}
.runs-table a.run-link:hover {
    color: #FFE082;
    border-bottom-color: #FFE082;
}
"""

    token_depth_css = """
/* 2D/3D token-depth bar rendering */
.chart-area.svg-iso .models-row {
    z-index: 5;
}
.chart-area.svg-iso.token-depth-3d .models-row {
    gap: 72px;
}
.chart-area.svg-iso .bars-row {
    gap: 8px;
    align-items: flex-end;
}
.chart-area.svg-iso.three-bars.token-depth-3d .bars-row {
    gap: 6px;
}
.chart-area.svg-iso .bar-wrapper {
    margin-right: 0;
}
.chart-area.svg-iso.token-depth-3d .bar-wrapper {
    margin-right: var(--iso-depth, 0px);
}
.chart-area.svg-iso.three-bars.token-depth-3d .bar-wrapper {
    margin-right: var(--iso-spacing, 0px);
}
.chart-area.svg-iso .bar-link {
    overflow: visible;
}
.chart-area.svg-iso .bar {
    --iso-depth: 16px;
    margin-right: 0;
    filter: drop-shadow(0 7px 15px rgba(0,0,0,0.30));
}
.chart-area.svg-iso .bar-inner {
    position: relative;
    z-index: 3;
}
.chart-area.svg-iso .bar-segments {
    box-shadow:
        inset 0 1px 0 rgba(255,255,255,0.18),
        inset -4px 0 8px rgba(0,0,0,0.12),
        inset 5px 0 8px rgba(255,255,255,0.05);
}
.chart-area.svg-iso .bar-wrapper.token-missing .bar {
    opacity: 0.92;
}
.svg-iso-legend {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    padding: 6px 10px;
    border-radius: 8px;
    background: rgba(255,255,255,0.06);
    border: 1px solid rgba(255,255,255,0.10);
    color: #c9d1d9;
    cursor: pointer;
    font-size: 0.85rem;
    font-weight: 600;
    white-space: nowrap;
    user-select: none;
    transition: opacity 0.25s ease, transform 0.15s ease, border-color 0.2s ease, background 0.2s ease;
}
.svg-iso-legend:hover {
    transform: translateY(-1px);
    border-color: #FFCC33;
}
.svg-iso-legend.active {
    border-color: #FFCC33;
    background: rgba(255,204,51,0.10);
    color: #FFE680;
}
.svg-iso-legend.dimmed {
    opacity: 0.45;
}
.svg-iso-swatch {
    position: relative;
    width: 24px;
    height: 14px;
    border-radius: 3px;
    background: linear-gradient(135deg, #FFCC33, #58d68d);
    box-shadow: 0 5px 10px rgba(0,0,0,0.28);
}
.svg-iso-swatch::before {
    content: '';
    position: absolute;
    left: 100%;
    top: -5px;
    width: 12px;
    height: 14px;
    transform: skewY(-24deg);
    transform-origin: left bottom;
    border-radius: 0 4px 3px 0;
    background: rgba(255,204,51,0.38);
}
.svg-iso-swatch::after {
    content: '';
    position: absolute;
    left: 6px;
    bottom: 100%;
    width: 24px;
    height: 6px;
    transform: skewX(-49deg);
    transform-origin: left bottom;
    border-radius: 3px 3px 0 0;
    background: rgba(255,255,255,0.28);
}
.svg-iso-split {
    position: absolute;
    left: 78%;
    top: -4px;
    width: 2px;
    height: 20px;
    border-radius: 999px;
    background: rgba(255,255,255,0.86);
    box-shadow: 0 0 0 1px rgba(0,0,0,0.30), 0 0 7px rgba(255,255,255,0.24);
    z-index: 2;
}
.chart-area.svg-iso.token-depth-flat .models-row,
.chart-area.svg-iso.token-depth-off .models-row {
    gap: 64px;
}
.chart-area.svg-iso.token-depth-flat .bar,
.chart-area.svg-iso.token-depth-off .bar {
    filter: none;
}
.chart-area.svg-iso.token-depth-flat .bar-wrapper,
.chart-area.svg-iso.token-depth-off .bar-wrapper {
    margin-right: 0;
}
.chart-area.svg-iso.token-depth-flat .bar-link:hover .bar,
.chart-area.svg-iso.token-depth-off .bar-link:hover .bar {
    filter: brightness(1.15);
}
.chart-area.svg-iso.token-depth-flat .bar-segments,
.chart-area.svg-iso.token-depth-off .bar-segments {
    box-shadow: none;
}
.chart-area.three-bars .three-bars-canvas {
    position: absolute;
    left: 0;
    top: 0;
    overflow: visible;
    pointer-events: none;
    z-index: 2;
}
.chart-area.three-bars .three-bars-depth-label-layer {
    position: absolute;
    left: 0;
    top: 0;
    overflow: visible;
    pointer-events: none;
    z-index: 12;
}
.chart-area.three-bars:not(.token-depth-3d) .three-bars-depth-label-layer {
    display: none;
}
.three-bars-depth-label {
    position: absolute;
    display: inline-block;
    color: white;
    font-size: 0.78rem;
    font-weight: 800;
    line-height: 1;
    letter-spacing: 0.02em;
    white-space: nowrap;
    transform-origin: 0 50%;
    text-shadow:
        -1px -1px 0 rgba(0,0,0,0.8),
         1px -1px 0 rgba(0,0,0,0.8),
        -1px  1px 0 rgba(0,0,0,0.8),
         1px  1px 0 rgba(0,0,0,0.8),
         0 0 6px rgba(0,0,0,0.6);
}
.three-bars-depth-label[data-depth-mode="cost"] {
    font-size: 0.76rem;
}
.three-bars-depth-label[data-depth-mode="cost-shadow"] {
    color: #d8dee9;
    font-size: 0.72rem;
    opacity: 0.82;
}
.chart-area.three-bars.token-depth-3d .bar {
    filter: none;
}
.chart-area.three-bars.token-depth-3d:not(.three-bars-ready) .three-bars-canvas {
    visibility: hidden;
}
.chart-area.three-bars.three-bars-ready.token-depth-3d .bar-segments {
    opacity: 0;
    box-shadow: none !important;
}
.chart-area.three-bars.token-depth-3d .bar-top-label,
.chart-area.three-bars.token-depth-3d .bar-bottom-label {
    z-index: 4;
}
.chart-area.three-bars.token-depth-3d .bar-labels {
    z-index: 4;
}
"""

    # Build runs table HTML
    runs_table_html = _build_runs_table_html(runs or [], weave_run_urls=weave_run_urls)

    # ------------------------------------------------------------------
    # JavaScript for interactivity
    # Defined as regular Python strings to avoid f-string brace escaping.
    # Interpolated into the HTML template via {all_js}.
    # ------------------------------------------------------------------
    _agent_ver_js_entries = []
    for _ak, _av in _agent_version_map.items():
        _agent_ver_js_entries.append(f"        '{_ak}': '{_av}'")
    _agent_versions_js = (
        "    var agentVersions = {\n"
        + ",\n".join(_agent_ver_js_entries)
        + "\n    };"
    )

    url_state_js = """(function() {
    var MANAGED_PARAMS = ['agents', 'agentOrder', 'models', 'modelOrder', 'metric', 'unit', 'barSort', 'runSort', '3D', '3d', 'tokenDepth'];
    var params = new URLSearchParams(window.location.search);

    function listParam(name) {
        if (!params.has(name)) return null;
        var raw = params.get(name) || '';
        if (!raw) return [];
        return raw.split(',').map(function(v) { return v.trim(); }).filter(Boolean);
    }

    function listFrom(selector, attr) {
        return Array.prototype.slice.call(document.querySelectorAll(selector)).map(function(el) {
            return el.getAttribute(attr);
        }).filter(Boolean);
    }

    function sameList(a, b) {
        if (!a || !b || a.length !== b.length) return false;
        for (var i = 0; i < a.length; i++) {
            if (a[i] !== b[i]) return false;
        }
        return true;
    }

    function parseBarSort() {
        var raw = params.get('barSort');
        var mode = raw == null ? 0 : parseInt(raw, 10);
        return (mode >= 0 && mode <= 2) ? mode : 0;
    }

    function parseRunSort() {
        var raw = params.get('runSort') || '';
        var m = raw.match(/^(\\d+):(asc|desc)$/);
        if (!m) return null;
        return {col: parseInt(m[1], 10), dir: m[2]};
    }

    function parseTokenDepth() {
        var raw = (params.get('3D') || params.get('3d') || params.get('tokenDepth') || '').toLowerCase();
        if (raw === 'overlap' || raw === 'spaced' || raw === 'on' || raw === '3d') return 'tokens';
        if (raw === 'tokens' || raw === 'token') return 'tokens';
        if (raw === 'cost' || raw === 'costs' || raw === 'usd') return 'cost';
        if (raw === 'both' || raw === 'tokens+cost' || raw === 'tokens-cost' || raw === 'token+cost' || raw === 'token-cost' || raw === 'tokens_cost' || raw === 'combined') return 'both';
        return 'flat';
    }

    var api = window.WolfBenchUrlState = {
        booting: true,
        defaults: {
            agentOrder: listFrom('.legend-agent', 'data-agent'),
            modelOrder: listFrom('.model-btn', 'data-model')
        },
        state: {
            agents: listParam('agents'),
            agentOrder: listParam('agentOrder'),
            models: listParam('models'),
            modelOrder: listParam('modelOrder'),
            metric: params.get('metric') || null,
            unit: params.get('unit') || 'pct',
            barSort: parseBarSort(),
            runSort: parseRunSort(),
            tokenDepth: parseTokenDepth()
        },
        notifyChange: notifyChange,
        finishBoot: finishBoot,
        sameList: sameList
    };

    function captureParams() {
        var out = new URLSearchParams(window.location.search);
        MANAGED_PARAMS.forEach(function(k) { out.delete(k); });

        var allAgents = listFrom('.legend-agent', 'data-agent');
        var availableAgents = listFrom('.legend-agent:not(.unavailable)', 'data-agent');
        var agentBaseline = availableAgents.length ? availableAgents : allAgents;
        var activeAgents = listFrom('.legend-agent:not(.dimmed):not(.unavailable)', 'data-agent');
        if (agentBaseline.length && activeAgents.length > 0 && activeAgents.length < agentBaseline.length) {
            out.set('agents', activeAgents.join(','));
        }

        var agentOrder = window._getAgentOrderForUrl
            ? window._getAgentOrderForUrl()
            : listFrom('.legend-agent', 'data-agent');
        if (agentOrder && !sameList(agentOrder, api.defaults.agentOrder)) {
            out.set('agentOrder', agentOrder.join(','));
        }

        var allModels = listFrom('.model-btn', 'data-model');
        var activeModels = listFrom('.model-btn:not(.dimmed)', 'data-model');
        if (allModels.length && activeModels.length < allModels.length) {
            out.set('models', activeModels.join(','));
        }

        var modelOrder = window._getModelOrderForUrl ? window._getModelOrderForUrl() : null;
        if (modelOrder && !sameList(modelOrder, api.defaults.modelOrder)) {
            out.set('modelOrder', modelOrder.join(','));
        }

        var metric = window._filterMetric || '';
        if (metric) out.set('metric', metric);

        var tokenDepthMode = (typeof window._tokenDepthMode === 'string')
            ? window._tokenDepthMode
            : api.state.tokenDepth;
        if (tokenDepthMode === 'tokens') {
            out.set('3D', 'tokens');
        } else if (tokenDepthMode === 'cost') {
            out.set('3D', 'cost');
        } else if (tokenDepthMode === 'both') {
            out.set('3D', 'both');
        }

        var unitToggle = document.getElementById('unitToggle');
        var unit = unitToggle ? unitToggle.getAttribute('data-mode') : 'pct';
        if (unit === 'abs') out.set('unit', 'abs');

        var barSortToggle = document.getElementById('barSortToggle');
        var barSort = barSortToggle ? barSortToggle.getAttribute('data-sort-mode') : '0';
        if (barSort && barSort !== '0') out.set('barSort', barSort);

        var table = document.querySelector('.runs-table');
        if (table && table.tHead && table.tHead.rows[0]) {
            var headers = table.tHead.rows[0].cells;
            for (var i = 0; i < headers.length; i++) {
                var dir = headers[i].getAttribute('data-sort');
                if (dir) {
                    if (!(i === 0 && dir === 'desc')) out.set('runSort', i + ':' + dir);
                    break;
                }
            }
        }

        return out;
    }

    var notifyTimer = null;
    function replaceUrlNow() {
        var out = captureParams();
        var query = out.toString();
        var next = window.location.pathname + (query ? '?' + query : '') + window.location.hash;
        var current = window.location.pathname + window.location.search + window.location.hash;
        if (next !== current) {
            window.history.replaceState(null, '', next);
        }
    }

    function notifyChange() {
        if (api.booting) return;
        clearTimeout(notifyTimer);
        notifyTimer = setTimeout(replaceUrlNow, 0);
    }

    function finishBoot() {
        api.booting = false;
        if (window.updateChartWidth) window.updateChartWidth();
        if (window.filterRunsTable) window.filterRunsTable();
        if (window.adjustLabelPadding) window.adjustLabelPadding();
        replaceUrlNow();
    }
})();"""

    longpress_js = """(function() {
    // Long-press detection for touch AND mouse (acts as Shift/Ctrl+Click)
    var LP_MS = 400;
    window._longPressed = false;
    function addLongPress(el) {
        var timer = null;
        function start() { window._longPressed = false; timer = setTimeout(function() { window._longPressed = true; }, LP_MS); }
        function cancel() { clearTimeout(timer); window._longPressed = false; }
        function stop() { clearTimeout(timer); }
        // Touch
        el.addEventListener('touchstart', start, {passive: true});
        el.addEventListener('touchend', stop);
        el.addEventListener('touchmove', cancel, {passive: true});
        el.addEventListener('touchcancel', cancel);
        // Mouse
        el.addEventListener('mousedown', start);
        el.addEventListener('mouseup', stop);
        el.addEventListener('mouseleave', cancel);
    }
    document.querySelectorAll('.legend-agent, .model-btn').forEach(addLongPress);
})();"""

    agent_toggle_js = """(function() {
AGENT_VERSIONS_PLACEHOLDER
    var agentLegends = document.querySelectorAll('.legend-agent');
    var barWrappers = document.querySelectorAll('.bar-wrapper');
    var modelGroups = document.querySelectorAll('.model-group');
    var modelsRow = document.querySelector('.models-row');
    var modelBar = document.querySelector('.model-bar');
    var versionLine = document.getElementById('agentVersionLine');
    var versionLineDefault = versionLine ? versionLine.innerHTML : '';
    var urlState = window.WolfBenchUrlState ? window.WolfBenchUrlState.state : {};
    function notifyUrlChange() {
        if (window.WolfBenchUrlState) window.WolfBenchUrlState.notifyChange();
    }

    // Shared filter state (agents initialized after allAgentIds is built)
    window._filterAgents = {};
    window._filterMetric = null;

    // Highlight the metric labels used for sorting in golden
    function highlightSortMetric(metric) {
        var m = metric || 'average';
        document.querySelectorAll('.seg-label').forEach(function(lbl) {
            if (lbl.getAttribute('data-metric') === m) {
                lbl.classList.add('seg-label-sort');
            } else {
                lbl.classList.remove('seg-label-sort');
            }
        });
    }
    // Apply on initial load
    highlightSortMetric(null);

    // Check if only one agent exists at load time
    var initAgents = {};
    barWrappers.forEach(function(b) { initAgents[b.getAttribute('data-agent')] = true; });
    var chartAreaInit = document.querySelector('.chart-area');
    if (chartAreaInit) chartAreaInit.classList.toggle('single-agent', Object.keys(initAgents).length <= 1);

    // Reorder models by cascading agent priority (agent-bar order = sort priority).
    // Within each agent, cascade through metrics before moving to the next agent:
    // primary metric (filter or 'average') first, then remaining metrics in legend order.
    window.reorderModels = function() {
        if (!modelsRow) return;
        var agentBarEl = document.querySelector('.agent-bar');
        var agentOrder = agentBarEl
            ? Array.from(agentBarEl.querySelectorAll('.legend-agent:not(.dimmed):not(.unavailable)')).map(function(b) { return b.getAttribute('data-agent'); })
            : [];
        var primary = window._filterMetric || 'average';
        var legendOrder = ['ceiling', 'best', 'average', 'worst', 'solid'];
        var metricOrder = [primary].concat(legendOrder.filter(function(k) { return k !== primary; }));
        // Use raw (unrounded) values to avoid rounding ties (e.g. 63 vs 64 both showing as 71%).
        var rawKey = {ceiling: 'ceiling_raw', best: 'best_raw', average: 'average_raw',
                      worst: 'worst_raw', solid: 'solid_raw'};
        var groups = Array.from(modelsRow.querySelectorAll('.model-group'));
        groups.sort(function(a, b) {
            try {
                var ja = JSON.parse(a.getAttribute('data-scores') || '{}');
                var jb = JSON.parse(b.getAttribute('data-scores') || '{}');
                for (var i = 0; i < agentOrder.length; i++) {
                    var ag = agentOrder[i];
                    for (var j = 0; j < metricOrder.length; j++) {
                        var mk = rawKey[metricOrder[j]];
                        var sa = (ja[ag] && ja[ag][mk] != null) ? ja[ag][mk] : -1;
                        var sb = (jb[ag] && jb[ag][mk] != null) ? jb[ag][mk] : -1;
                        if (sa !== sb) return sb - sa;
                    }
                }
            } catch(e) {}
            return 0;
        });
        groups.forEach(function(g) { modelsRow.appendChild(g); });
        if (modelBar) {
            var btnMap = {};
            Array.from(modelBar.querySelectorAll('.model-btn')).forEach(function(b) {
                btnMap[b.getAttribute('data-model')] = b;
            });
            groups.forEach(function(g) {
                var btn = btnMap[g.getAttribute('data-model')];
                if (btn) modelBar.appendChild(btn);
            });
        }
        highlightSortMetric(window._filterMetric);
    };

    // Collect all agent IDs and init filter with all active
    var allAgentIds = [];
    agentLegends.forEach(function(l) { var a = l.getAttribute('data-agent'); if (a) allAgentIds.push(a); });
    var agentFilterMode = 'all';
    function setAllAgentsActive() {
        window._filterAgents = {};
        allAgentIds.forEach(function(a) { window._filterAgents[a] = true; });
        agentFilterMode = 'all';
    }
    setAllAgentsActive();
    if (urlState.agents) {
        var initialAgents = {};
        urlState.agents.forEach(function(a) {
            if (allAgentIds.indexOf(a) !== -1) initialAgents[a] = true;
        });
        if (Object.keys(initialAgents).length > 0) {
            window._filterAgents = initialAgents;
            agentFilterMode = Object.keys(initialAgents).length === allAgentIds.length ? 'all' : 'subset';
        }
    }

    function groupHasUsableAgentBar(group, agent) {
        var bar = group.querySelector('.bar-wrapper[data-agent="' + agent + '"]');
        if (!bar || bar.classList.contains('bar-dismissed')) return false;
        if (window._filterMetric && bar.getAttribute('data-runs') === '1') return false;
        return true;
    }

    function availableAgentIds(available) {
        var ids = allAgentIds.filter(function(a) { return available[a] !== false; });
        return ids;
    }

    window.syncAgentAvailability = function() {
        var available = {};
        allAgentIds.forEach(function(a) { available[a] = false; });
        modelGroups.forEach(function(g) {
            if (g.classList.contains('model-hidden-user') || g.classList.contains('metric-hidden')) return;
            allAgentIds.forEach(function(a) {
                if (!available[a] && groupHasUsableAgentBar(g, a)) available[a] = true;
            });
        });
        agentLegends.forEach(function(l) {
            var a = l.getAttribute('data-agent');
            var isAvailable = available[a] !== false;
            l.classList.toggle('unavailable', !isAvailable);
            l.hidden = !isAvailable;
            l.setAttribute('aria-hidden', isAvailable ? 'false' : 'true');
            l.setAttribute('draggable', (isAvailable && window._barSortMode !== 2) ? 'true' : 'false');
            if (!isAvailable) {
                l.classList.remove('dragging');
                l.classList.remove('drag-over');
            }
        });
        return available;
    };

    function effectiveAgentSelection(available) {
        var ids = availableAgentIds(available);
        var selected = {};
        if (agentFilterMode === 'all') {
            ids.forEach(function(a) { selected[a] = true; });
        } else {
            ids.forEach(function(a) {
                if (window._filterAgents[a]) selected[a] = true;
            });
            if (Object.keys(selected).length === 0) {
                setAllAgentsActive();
                ids.forEach(function(a) { selected[a] = true; });
            }
        }
        return {selected: selected, availableIds: ids};
    }

    function syncModelButtonAvailability() {
        if (!modelBar) return;
        var groupMap = {};
        modelGroups.forEach(function(g) {
            groupMap[g.getAttribute('data-model')] = g;
        });
        Array.prototype.slice.call(modelBar.querySelectorAll('.model-btn')).forEach(function(btn) {
            var g = groupMap[btn.getAttribute('data-model')];
            var isAvailable = !g || (
                !g.classList.contains('model-hidden') &&
                !g.classList.contains('metric-hidden')
            );
            btn.classList.toggle('unavailable', !isAvailable);
            btn.hidden = !isAvailable;
            btn.setAttribute('aria-hidden', isAvailable ? 'false' : 'true');
            btn.setAttribute('draggable', isAvailable ? 'true' : 'false');
            if (!isAvailable) {
                btn.classList.remove('dragging');
                btn.classList.remove('drag-over');
            }
        });
    }

    // Apply current agent filter state to DOM
    function applyAgentFilter() {
        var available = window.syncAgentAvailability();
        var effective = effectiveAgentSelection(available);
        var sel = effective.selected;
        var nSel = Object.keys(sel).length;
        var allActive = nSel === effective.availableIds.length;

        // Reset
        agentLegends.forEach(function(l) { l.classList.remove('dimmed'); });
        barWrappers.forEach(function(b) { b.classList.remove('agent-hidden'); });
        modelGroups.forEach(function(g) { g.classList.remove('model-hidden'); });
        if (modelsRow) modelsRow.classList.remove('agent-filtered');

        if (!allActive && nSel > 0) {
            // Subset selected: show only those
            agentLegends.forEach(function(l) {
                var a = l.getAttribute('data-agent');
                l.classList.toggle('dimmed', available[a] !== false && !sel[a]);
            });
            barWrappers.forEach(function(b) {
                b.classList.toggle('agent-hidden', !sel[b.getAttribute('data-agent')]);
            });
            modelGroups.forEach(function(g) {
                var hasAgent = false;
                for (var a in sel) {
                    if (groupHasUsableAgentBar(g, a)) {
                        hasAgent = true; break;
                    }
                }
                g.classList.toggle('model-hidden', !hasAgent);
            });
            if (modelsRow) modelsRow.classList.add('agent-filtered');
            if (nSel === 1 && versionLine) {
                var singleAgent = Object.keys(sel)[0];
                versionLine.innerHTML = agentVersions[singleAgent] || versionLineDefault;
            } else if (versionLine) {
                versionLine.innerHTML = versionLineDefault;
            }
	        } else {
	            // All active — no filter
	            if (versionLine) versionLine.innerHTML = versionLineDefault;
	        }
	        if (window.WolfBenchClearHiddenModelHighlights) window.WolfBenchClearHiddenModelHighlights();
	        syncModelButtonAvailability();
        // Count visible agents — hide top labels when only one is shown
        var visibleAgents = {};
        modelGroups.forEach(function(g) {
            if (g.classList.contains('model-hidden') || g.classList.contains('model-hidden-user') || g.classList.contains('metric-hidden')) return;
            g.querySelectorAll('.bar-wrapper:not(.agent-hidden)').forEach(function(b) {
                if (b.classList.contains('bar-dismissed')) return;
                if (window._filterMetric && b.getAttribute('data-runs') === '1') return;
                visibleAgents[b.getAttribute('data-agent')] = true;
            });
        });
        var chartArea = document.querySelector('.chart-area');
        if (chartArea) chartArea.classList.toggle('single-agent', Object.keys(visibleAgents).length <= 1);

        window.reorderModels();
        if (window.updateChartWidth) window.updateChartWidth();
        if (window.filterRunsTable) window.filterRunsTable();
    }
    window.applyAgentFilter = applyAgentFilter;

    // Drag to reorder agents (reorders bar-wrappers inside each model group)
    var agentBar = document.querySelector('.agent-bar');
    var agentDragSrc = null;

    function currentAgentOrder() {
        return Array.prototype.slice.call(agentBar.querySelectorAll('.legend-agent')).map(function(b) {
            return b.getAttribute('data-agent');
        });
    }

    function applyAgentOrder(order) {
        if (!agentBar || !order || !order.length) return;
        var btnMap = {};
        Array.prototype.slice.call(agentBar.querySelectorAll('.legend-agent')).forEach(function(b) {
            btnMap[b.getAttribute('data-agent')] = b;
        });
        order.forEach(function(a) {
            if (btnMap[a]) agentBar.appendChild(btnMap[a]);
        });
        allAgentIds.forEach(function(a) {
            if (order.indexOf(a) === -1 && btnMap[a]) agentBar.appendChild(btnMap[a]);
        });
    }

    applyAgentOrder(urlState.agentOrder);

    function reorderBarsToMatchAgentButtons() {
        var order = currentAgentOrder();
        // Within-agent tiebreaker: score cascade using raw values
        var primary = window._filterMetric || 'average';
        var legendOrder = ['ceiling', 'best', 'average', 'worst', 'solid'];
        var metricOrder = [primary].concat(legendOrder.filter(function(k) { return k !== primary; }));
        var rawKey = {ceiling: 'ceiling_raw', best: 'best_raw', average: 'average_raw',
                      worst: 'worst_raw', solid: 'solid_raw'};
        document.querySelectorAll('.bars-row').forEach(function(row) {
            var wrappers = Array.prototype.slice.call(row.querySelectorAll('.bar-wrapper'));
            wrappers.sort(function(a, b) {
                var ai = order.indexOf(a.getAttribute('data-agent'));
                var bi = order.indexOf(b.getAttribute('data-agent'));
                if (ai !== bi) return ai - bi;
                // Same agent: cascade metrics (primary first, then legend order)
                try {
                    var sa = JSON.parse(a.getAttribute('data-bar-scores') || '{}');
                    var sb = JSON.parse(b.getAttribute('data-bar-scores') || '{}');
                    for (var j = 0; j < metricOrder.length; j++) {
                        var mk = rawKey[metricOrder[j]];
                        var va = sa[mk] != null ? sa[mk] : -1;
                        var vb = sb[mk] != null ? sb[mk] : -1;
                        if (va !== vb) return vb - va;
                    }
                } catch(e) {}
                return 0;
            });
            wrappers.forEach(function(w) { row.appendChild(w); });
        });
    }

    agentLegends.forEach(function(btn) {
        btn.addEventListener('dragstart', function(e) {
            if (btn.classList.contains('unavailable') || btn.getAttribute('draggable') === 'false') {
                e.preventDefault();
                return;
            }
            agentDragSrc = btn;
            btn.classList.add('dragging');
            e.dataTransfer.effectAllowed = 'move';
            e.dataTransfer.setData('text/plain', btn.getAttribute('data-agent'));
        });
        btn.addEventListener('dragend', function() {
            btn.classList.remove('dragging');
            btn.setAttribute('data-just-dragged', 'true');
            setTimeout(function() { btn.removeAttribute('data-just-dragged'); }, 50);
            agentLegends.forEach(function(b) { b.classList.remove('drag-over'); });
            agentDragSrc = null;
        });
        btn.addEventListener('dragover', function(e) {
            if (!agentDragSrc || btn.classList.contains('unavailable')) return;
            e.preventDefault();
            e.dataTransfer.dropEffect = 'move';
            if (btn !== agentDragSrc) btn.classList.add('drag-over');
        });
        btn.addEventListener('dragleave', function() { btn.classList.remove('drag-over'); });
        btn.addEventListener('drop', function(e) {
            e.preventDefault();
            btn.classList.remove('drag-over');
            if (!agentDragSrc || agentDragSrc === btn || btn.classList.contains('unavailable')) return;
            var allBtns = Array.prototype.slice.call(agentBar.querySelectorAll('.legend-agent'));
            var srcIdx = allBtns.indexOf(agentDragSrc);
            var tgtIdx = allBtns.indexOf(btn);
            if (srcIdx < tgtIdx) {
                agentBar.insertBefore(agentDragSrc, btn.nextSibling);
            } else {
                agentBar.insertBefore(agentDragSrc, btn);
            }
            reorderBarsToMatchAgentButtons();
            window.reorderModels();
            notifyUrlChange();
        });
    });

    agentLegends.forEach(function(el) {
        el.addEventListener('click', function(e) {
            e.stopPropagation();
            var _lp = window._longPressed; window._longPressed = false;
            if (el.getAttribute('data-just-dragged') === 'true') {
                el.removeAttribute('data-just-dragged');
                return;
            }
            if (el.classList.contains('unavailable')) return;
            var agent = el.getAttribute('data-agent');
            if (!agent) return;
            var available = window.syncAgentAvailability();
            var ids = availableAgentIds(available);

            if (e.ctrlKey || e.metaKey || e.shiftKey || _lp) {
                if (agentFilterMode === 'all') {
                    window._filterAgents = {};
                    ids.forEach(function(a) { window._filterAgents[a] = true; });
                }
                agentFilterMode = 'subset';
                // Toggle this agent
                if (window._filterAgents[agent]) {
                    delete window._filterAgents[agent];
                } else {
                    window._filterAgents[agent] = true;
                }
                // None active → all active
                if (!ids.some(function(a) { return window._filterAgents[a]; })) {
                    setAllAgentsActive();
                }
            } else {
                // Exclusive select (or deselect if only active)
                var selectedAvailable = ids.filter(function(a) { return window._filterAgents[a]; });
                if (agentFilterMode === 'subset' && selectedAvailable.length === 1 && selectedAvailable[0] === agent) {
                    setAllAgentsActive();
                } else {
                    agentFilterMode = 'subset';
                    window._filterAgents = {};
                    window._filterAgents[agent] = true;
                }
            }
            applyAgentFilter();
            notifyUrlChange();
        });
    });

    // Bar sort toggle: 3-mode cycle
    //   0 = bars by agent order, models by agent-priority cascade (default)
    //   1 = bars by score within model, models by agent-priority cascade
    //   2 = bars by score within model, models by max score across visible agents
    var barSortMode = 0;
    var barSortToggle = document.getElementById('barSortToggle');

    function reorderBarsByScore() {
        // Use raw (absolute count) keys so ties on rounded % break correctly.
        var m = (window._filterMetric || 'average') + '_raw';
        document.querySelectorAll('.bars-row').forEach(function(row) {
            var wrappers = Array.prototype.slice.call(row.querySelectorAll('.bar-wrapper'));
            wrappers.sort(function(a, b) {
                try {
                    var sa = JSON.parse(a.getAttribute('data-bar-scores') || '{}');
                    var sb = JSON.parse(b.getAttribute('data-bar-scores') || '{}');
                    return (sb[m] || 0) - (sa[m] || 0);
                } catch(e) {}
                return 0;
            });
            wrappers.forEach(function(w) { row.appendChild(w); });
        });
    }

    function reorderModelsByMaxScore() {
        if (!modelsRow) return;
        var primary = window._filterMetric || 'average';
        var legendOrder = ['ceiling', 'best', 'average', 'worst', 'solid'];
        var metricOrder = [primary].concat(legendOrder.filter(function(k) { return k !== primary; }));
        var rawKey = {ceiling: 'ceiling_raw', best: 'best_raw', average: 'average_raw',
                      worst: 'worst_raw', solid: 'solid_raw'};
        var agentBarEl = document.querySelector('.agent-bar');
        var visibleAgents = agentBarEl
            ? Array.from(agentBarEl.querySelectorAll('.legend-agent:not(.dimmed):not(.unavailable)')).map(function(b) { return b.getAttribute('data-agent'); })
            : [];
        function maxFor(scores, metricKey) {
            var best = -1;
            for (var i = 0; i < visibleAgents.length; i++) {
                var ag = visibleAgents[i];
                var v = (scores[ag] && scores[ag][metricKey] != null) ? scores[ag][metricKey] : -1;
                if (v > best) best = v;
            }
            return best;
        }
        var groups = Array.from(modelsRow.querySelectorAll('.model-group'));
        groups.sort(function(a, b) {
            try {
                var ja = JSON.parse(a.getAttribute('data-scores') || '{}');
                var jb = JSON.parse(b.getAttribute('data-scores') || '{}');
                for (var j = 0; j < metricOrder.length; j++) {
                    var mk = rawKey[metricOrder[j]];
                    var sa = maxFor(ja, mk);
                    var sb = maxFor(jb, mk);
                    if (sa !== sb) return sb - sa;
                }
            } catch(e) {}
            return 0;
        });
        groups.forEach(function(g) { modelsRow.appendChild(g); });
        if (modelBar) {
            var btnMap = {};
            Array.from(modelBar.querySelectorAll('.model-btn')).forEach(function(b) {
                btnMap[b.getAttribute('data-model')] = b;
            });
            groups.forEach(function(g) {
                var btn = btnMap[g.getAttribute('data-model')];
                if (btn) modelBar.appendChild(btn);
            });
        }
        highlightSortMetric(window._filterMetric);
    }

    // Reorder agent buttons by their max score across the current model/metric view.
    // This is the Mode 2 stand-in for manual agent ordering while drag is disabled.
    function reorderAgentsByMaxScore() {
        var agentBarEl = document.querySelector('.agent-bar');
        if (!agentBarEl) return;
        var primary = window._filterMetric || 'average';
        var legendOrder = ['ceiling', 'best', 'average', 'worst', 'solid'];
        var metricOrder = [primary].concat(legendOrder.filter(function(k) { return k !== primary; }));
        var rawKey = {ceiling: 'ceiling_raw', best: 'best_raw', average: 'average_raw',
                      worst: 'worst_raw', solid: 'solid_raw'};
        var agentScores = {};
        document.querySelectorAll('.model-group').forEach(function(g) {
            if (g.classList.contains('model-hidden-user') || g.classList.contains('metric-hidden')) return;
            try {
                var scores = JSON.parse(g.getAttribute('data-scores') || '{}');
                for (var ag in scores) {
                    if (!agentScores[ag]) agentScores[ag] = {};
                    for (var j = 0; j < metricOrder.length; j++) {
                        var mk = rawKey[metricOrder[j]];
                        var v = scores[ag][mk] != null ? scores[ag][mk] : -1;
                        if (agentScores[ag][mk] == null || v > agentScores[ag][mk]) {
                            agentScores[ag][mk] = v;
                        }
                    }
                }
            } catch(e) {}
        });
        var btns = Array.prototype.slice.call(agentBarEl.querySelectorAll('.legend-agent'));
        btns.sort(function(a, b) {
            var sa = agentScores[a.getAttribute('data-agent')] || {};
            var sb = agentScores[b.getAttribute('data-agent')] || {};
            for (var j = 0; j < metricOrder.length; j++) {
                var mk = rawKey[metricOrder[j]];
                var va = sa[mk] != null ? sa[mk] : -1;
                var vb = sb[mk] != null ? sb[mk] : -1;
                if (va !== vb) return vb - va;
            }
            return 0;
        });
        btns.forEach(function(btn) { agentBarEl.appendChild(btn); });
    }

    // Snapshot/restore the user-controlled agent order around Mode 2.
    var savedAgentOrder = null;
    function snapshotAgentOrder() {
        var agentBarEl = document.querySelector('.agent-bar');
        if (!agentBarEl) return;
        savedAgentOrder = currentAgentOrder();
    }
    function restoreAgentOrder() {
        if (!savedAgentOrder) return;
        var agentBarEl = document.querySelector('.agent-bar');
        if (agentBarEl) {
            var btnMap = {};
            Array.prototype.slice.call(agentBarEl.querySelectorAll('.legend-agent')).forEach(function(b) {
                btnMap[b.getAttribute('data-agent')] = b;
            });
            savedAgentOrder.forEach(function(a) {
                if (btnMap[a]) agentBarEl.appendChild(btnMap[a]);
            });
        }
        savedAgentOrder = null;
    }
    window._getAgentOrderForUrl = function() {
        return savedAgentOrder ? savedAgentOrder.slice() : currentAgentOrder();
    };

    // Mode 2: agent button drag is meaningless (bars/models don't use agent order).
    // Disable native drag + apply a CSS hook to swap the cursor.
    function setAgentDragEnabled(enabled) {
        document.querySelectorAll('.legend-agent').forEach(function(b) {
            if (enabled && !b.classList.contains('unavailable')) {
                b.setAttribute('draggable', 'true');
            } else {
                b.setAttribute('draggable', 'false');
            }
        });
    }

    window._barSortMode = 0;
    function setBarSortMode(mode) {
        var prev = barSortMode;
        barSortMode = mode;
        window._barSortMode = barSortMode;
        if (barSortToggle) {
            barSortToggle.setAttribute('data-sort-mode', String(barSortMode));
            barSortToggle.classList.toggle('active', barSortMode > 0);
        }
        if (barSortMode === 2 && prev !== 2) {
            snapshotAgentOrder();
            setAgentDragEnabled(false);
        } else if (prev === 2 && barSortMode !== 2) {
            restoreAgentOrder();
            setAgentDragEnabled(true);
        }
        window.reorderModels();
    }
    if (barSortToggle) {
        barSortToggle.addEventListener('click', function() {
            setBarSortMode((barSortMode + 1) % 3);
            notifyUrlChange();
        });
    }

    // Hook into metric filter / agent filter changes to re-sort.
    // Mode 0: agent-priority cascade for models, agent-button order for bars.
    // Mode 1: agent-priority cascade for models, score order for bars.
    // Mode 2: max-score cascade for models, score order for bars.
    var origReorderModels = window.reorderModels;
    window.reorderModels = function() {
        if (window._barSortMode === 2) {
            reorderAgentsByMaxScore();
            reorderModelsByMaxScore();
        } else {
            origReorderModels();
        }
        if (window._barSortMode > 0) {
            reorderBarsByScore();
        } else {
            reorderBarsToMatchAgentButtons();
        }
    };
    applyAgentFilter();
    if (barSortToggle && urlState.barSort) {
        setBarSortMode(urlState.barSort);
    }
})();""".replace("AGENT_VERSIONS_PLACEHOLDER", _agent_versions_js)

    metric_filter_js = """(function() {
    var activeMetric = null;
    var chartArea = document.querySelector('.chart-area');
    var metricLegends = document.querySelectorAll('.legend-metric');
    var allLabels = document.querySelectorAll('.seg-label');
    var urlState = window.WolfBenchUrlState ? window.WolfBenchUrlState.state : {};
    function notifyUrlChange() {
        if (window.WolfBenchUrlState) window.WolfBenchUrlState.notifyChange();
    }

    // Save the collision-avoided positions on first load
    allLabels.forEach(function(lbl) {
        lbl.setAttribute('data-nudged-bottom', lbl.style.bottom);
    });

    function adjustLabelPositions(metric) {
        allLabels.forEach(function(lbl) {
            if (metric) {
                // Snap visible label to true Y position
                if (lbl.getAttribute('data-metric') === metric) {
                    lbl.style.bottom = lbl.getAttribute('data-true-bottom') + 'px';
                }
            } else {
                // Restore collision-avoided position
                lbl.style.bottom = lbl.getAttribute('data-nudged-bottom');
            }
        });
    }

    function adjustTopLabels(metric) {
        document.querySelectorAll('.bar-wrapper').forEach(function(wrapper) {
            var barInner = wrapper.querySelector('.bar-inner');
            var topLabel = wrapper.querySelector('.bar-top-label');
            if (!barInner || !topLabel) return;
            if (metric) {
                var ceilH = parseFloat(barInner.getAttribute('data-h-ceiling'));
                var metricH = parseFloat(barInner.getAttribute('data-h-' + metric));
                topLabel.style.transform = 'translateX(-50%) translateY(' + (ceilH - metricH) + 'px)';
            } else {
                topLabel.style.transform = '';
            }
        });
    }

    // Hide model groups where all bars are hidden (e.g. single-run models during metric filter)
    function hideEmptyGroups(active) {
	        document.querySelectorAll('.model-group').forEach(function(g) {
	            if (active) {
	                var hasBars = g.querySelector('.bar-wrapper:not(.agent-hidden):not([data-runs="1"])') !== null;
	                g.classList.toggle('metric-hidden', !hasBars);
	            } else {
	                g.classList.remove('metric-hidden');
	            }
	        });
	        if (window.WolfBenchClearHiddenModelHighlights) window.WolfBenchClearHiddenModelHighlights();
	    }

    function setMetricFilter(metric) {
        if (!chartArea) return;
        activeMetric = metric || null;
        chartArea.className = chartArea.className.replace(/metric-filter-\\w+/g, '').trim();
        if (!activeMetric) {
            metricLegends.forEach(function(l) {
                l.classList.remove('active');
                l.classList.remove('dimmed');
            });
            adjustLabelPositions(null);
            adjustTopLabels(null);
            hideEmptyGroups(false);
            window._filterMetric = null;
        } else {
            chartArea.classList.add('metric-filter-' + activeMetric);
            metricLegends.forEach(function(l) {
                var isActive = l.getAttribute('data-metric') === activeMetric;
                l.classList.toggle('active', isActive);
                l.classList.toggle('dimmed', !isActive);
            });
            adjustLabelPositions(activeMetric);
            adjustTopLabels(activeMetric);
            hideEmptyGroups(true);
            window._filterMetric = activeMetric;
        }
        if (window.applyAgentFilter) {
            window.applyAgentFilter();
        } else {
            window.reorderModels();
            if (window.updateChartWidth) window.updateChartWidth();
            if (window.filterRunsTable) window.filterRunsTable();
        }
        notifyUrlChange();
    }

    metricLegends.forEach(function(el) {
        el.addEventListener('click', function(e) {
            e.stopPropagation();
            var metric = el.getAttribute('data-metric');
            if (!metric) return;
            setMetricFilter(activeMetric === metric ? null : metric);
        });
    });
    if (urlState.metric) {
        metricLegends.forEach(function(el) {
            if (el.getAttribute('data-metric') === urlState.metric) setMetricFilter(urlState.metric);
        });
    }
})();"""

    unit_toggle_js = """(function() {
    var toggle = document.getElementById('unitToggle');
    if (!toggle) return;
    var urlState = window.WolfBenchUrlState ? window.WolfBenchUrlState.state : {};
    function notifyUrlChange() {
        if (window.WolfBenchUrlState) window.WolfBenchUrlState.notifyChange();
    }
    function setUnitMode(newMode, options) {
        if (newMode !== 'pct' && newMode !== 'abs') return;
        toggle.setAttribute('data-mode', newMode);
        toggle.textContent = (newMode === 'pct') ? '%' : '#';
        var attr = 'data-h-' + newMode;
        // Swap bar-inner total heights
        document.querySelectorAll('.bar-inner').forEach(function(el) {
            var h = el.getAttribute(attr);
            if (h && el.style.height !== h + 'px') el.style.height = h + 'px';
        });
        // Swap segment heights
        document.querySelectorAll('.segment').forEach(function(el) {
            var h = el.getAttribute(attr);
            if (h && el.style.height !== h + 'px') el.style.height = h + 'px';
        });
        // Swap label text
        document.querySelectorAll('.seg-pct').forEach(function(el) {
            var text = el.getAttribute('data-' + newMode);
            if (text != null && el.textContent !== text) el.textContent = text;
        });
        // Swap label positions
        document.querySelectorAll('.seg-label').forEach(function(el) {
            var b = el.getAttribute('data-bottom-' + newMode);
            if (b && el.style.bottom !== b + 'px') el.style.bottom = b + 'px';
        });
        // Swap y-axis ticks
        document.querySelectorAll('.y-tick').forEach(function(el) {
            var text = el.getAttribute('data-' + newMode);
            if (text != null && el.textContent !== text) el.textContent = text;
        });
        if (!options || !options.silent) notifyUrlChange();
    }
    window.WolfBenchApplyCurrentUnit = function() {
        setUnitMode(toggle.getAttribute('data-mode') || 'pct', {silent: true});
    };
    toggle.addEventListener('click', function() {
        var mode = toggle.getAttribute('data-mode');
        setUnitMode((mode === 'pct') ? 'abs' : 'pct');
    });
    if (urlState.unit === 'abs') setUnitMode('abs');
})();"""

    chart_screenshot_js = """(function() {
    var saveButton = document.getElementById('chartSaveToggle');
    if (!saveButton) return;
    var restoreTimers = new WeakMap();

    function rememberButtonDefaults(button) {
        if (!button || button._wolfbenchExportDefaults) return;
        button._wolfbenchExportDefaults = {
            text: button.textContent,
            title: button.getAttribute('title') || '',
            aria: button.getAttribute('aria-label') || button.getAttribute('title') || ''
        };
    }

    function setButtonState(button, state, text, title) {
        if (!button) return;
        rememberButtonDefaults(button);
        var defaults = button._wolfbenchExportDefaults;
        button.classList.remove('copying', 'saved', 'failed', 'partial');
        if (state) button.classList.add(state);
        button.textContent = text || defaults.text;
        button.setAttribute('title', title || defaults.title);
        button.setAttribute('aria-label', title || defaults.aria);
        if (restoreTimers.has(button)) clearTimeout(restoreTimers.get(button));
        if (state === 'saved' || state === 'failed' || state === 'partial') {
            restoreTimers.set(button, setTimeout(function() {
                button.classList.remove('saved', 'failed', 'partial');
                button.textContent = defaults.text;
                button.setAttribute('title', defaults.title);
                button.setAttribute('aria-label', defaults.aria);
            }, 2200));
        }
    }

    var html2canvasPromise = null;
    function loadHtml2Canvas() {
        if (window.html2canvas) return Promise.resolve(window.html2canvas);
        if (html2canvasPromise) return html2canvasPromise;
        html2canvasPromise = new Promise(function(resolve, reject) {
            var script = document.createElement('script');
            script.src = 'https://cdn.jsdelivr.net/npm/html2canvas@1.4.1/dist/html2canvas.min.js';
            script.async = true;
            script.crossOrigin = 'anonymous';
            script.onload = function() {
                if (window.html2canvas) resolve(window.html2canvas);
                else reject(new Error('Screenshot renderer did not initialize.'));
            };
            script.onerror = function() {
                reject(new Error('Could not load screenshot renderer.'));
            };
            document.head.appendChild(script);
        });
        return html2canvasPromise;
    }

    function canvasToBlob(canvas) {
        return new Promise(function(resolve, reject) {
            canvas.toBlob(function(blob) {
                if (blob) resolve(blob);
                else reject(new Error('Could not render chart PNG.'));
            }, 'image/png');
        });
    }

    function nextFrame() {
        return new Promise(function(resolve) { requestAnimationFrame(function() { resolve(); }); });
    }

    function numericPx(value) {
        var n = parseFloat(value);
        return Number.isFinite(n) ? n : 0;
    }

    function chartExportFilename() {
        var h1 = document.querySelector('h1');
        var text = h1 ? h1.textContent : '';
        var match = text.match(/\\(([^)]+)\\)/);
        var date = match ? match[1].trim() : new Date().toISOString().slice(0, 10);
        return 'wolfbench-chart-' + date + '.png';
    }

    function naturalElementWidth(el) {
        if (!el) return 0;
        var clone = el.cloneNode(true);
        clone.style.position = 'absolute';
        clone.style.left = '-100000px';
        clone.style.top = '0';
        clone.style.width = 'max-content';
        clone.style.maxWidth = 'none';
        clone.style.whiteSpace = 'nowrap';
        clone.style.visibility = 'hidden';
        clone.style.pointerEvents = 'none';
        document.body.appendChild(clone);
        var width = clone.getBoundingClientRect().width;
        clone.remove();
        return Math.ceil(width);
    }

    function elementVisible(el) {
        return !!(el && el.offsetParent !== null && !el.classList.contains('model-hidden') &&
            !el.classList.contains('model-hidden-user') && !el.classList.contains('metric-hidden'));
    }

    function headerMinExportWidth(header) {
        if (!header) return 0;
        var style = getComputedStyle(header);
        var gap = numericPx(style.columnGap || style.gap) || 24;
        var wolfLogo = header.querySelector('.header-logo-wolfbench');
        var wandbLogo = header.querySelector('.header-logo-wandb');
        var title = header.querySelector('h1');
        var titleWidth = naturalElementWidth(title);
        var leftCol = Math.max(72, naturalElementWidth(wolfLogo) || (wolfLogo ? wolfLogo.getBoundingClientRect().width : 0));
        var rightCol = Math.max(132, naturalElementWidth(wandbLogo) || (wandbLogo ? wandbLogo.getBoundingClientRect().width : 0));
        return Math.ceil(Math.max(112 + leftCol + titleWidth + rightCol + gap * 2 + 32, 860));
    }

    function visibleChartContentWidth(chartArea, modelsRow) {
        if (!chartArea) return 0;
        var areaRect = chartArea.getBoundingClientRect();
        var maxRight = 0;
        function includeRect(rect, extra) {
            if (!rect || (!rect.width && !rect.height)) return;
            maxRight = Math.max(maxRight, Math.ceil(rect.right - areaRect.left + (extra || 0)));
        }
        if (modelsRow) {
            Array.prototype.forEach.call(modelsRow.querySelectorAll('.model-group'), function(group) {
                if (!elementVisible(group)) return;
                includeRect(group.getBoundingClientRect());
                var barsRow = group.querySelector('.bars-row');
                var label = group.querySelector('.model-label');
                var highlight = group.querySelector('.model-highlight-box');
                includeRect(barsRow && barsRow.getBoundingClientRect());
                includeRect(label && label.getBoundingClientRect(), 8);
                includeRect(highlight && highlight.getBoundingClientRect());
            });
        }
        Array.prototype.forEach.call(chartArea.querySelectorAll('.bar-wrapper:not(.agent-hidden):not(.bar-dismissed)'), function(wrapper) {
            if (wrapper.offsetParent === null) return;
            var inner = wrapper.querySelector('.bar-inner') || wrapper.querySelector('.bar');
            if (!inner) return;
            var depth = parseFloat(wrapper.getAttribute('data-token-depth')) || 0;
            includeRect(inner.getBoundingClientRect(), Math.max(0, depth * 0.74) + 16);
        });
        Array.prototype.forEach.call(chartArea.querySelectorAll('.three-bars-depth-label'), function(label) {
            if (label.offsetParent === null) return;
            includeRect(label.getBoundingClientRect(), 8);
        });
        if (modelsRow) {
            var rowStyle = getComputedStyle(modelsRow);
            maxRight += numericPx(rowStyle.paddingRight) || 48;
        }
        return Math.ceil(Math.max(0, maxRight));
    }

    function visibleChartContentBottom(chartArea, modelsRow) {
        if (!chartArea) return 0;
        var areaRect = chartArea.getBoundingClientRect();
        var maxBottom = Math.ceil(Math.max(chartArea.scrollHeight || 0, areaRect.height || 0));
        function includeRect(rect, extra) {
            if (!rect || (!rect.width && !rect.height)) return;
            maxBottom = Math.max(maxBottom, Math.ceil(rect.bottom - areaRect.top + (extra || 0)));
        }
        if (modelsRow) {
            Array.prototype.forEach.call(modelsRow.querySelectorAll('.model-group'), function(group) {
                if (!elementVisible(group)) return;
                var barsRow = group.querySelector('.bars-row');
                var label = group.querySelector('.model-label');
                var highlight = group.querySelector('.model-highlight-box');
                includeRect(group.getBoundingClientRect());
                includeRect(barsRow && barsRow.getBoundingClientRect());
                includeRect(label && label.getBoundingClientRect(), 10);
                includeRect(highlight && highlight.getBoundingClientRect(), 6);
            });
        }
        Array.prototype.forEach.call(chartArea.querySelectorAll('.three-bars-depth-label'), function(label) {
            if (label.offsetParent === null) return;
            includeRect(label.getBoundingClientRect(), 8);
        });
        return Math.ceil(Math.max(0, maxBottom));
    }

    function chartExportRenderScale(width, height) {
        var desired = Math.max(2, window.devicePixelRatio || 1);
        var maxDimension = 16000;
        var maxPixels = 64000000;
        var dimensionScale = maxDimension / Math.max(width || 1, height || 1);
        var areaScale = Math.sqrt(maxPixels / Math.max(1, (width || 1) * (height || 1)));
        return Math.max(1, Math.min(desired, dimensionScale, areaScale));
    }

	    function exportCssText() {
	        var css = Array.prototype.slice.call(document.querySelectorAll('style')).map(function(style) {
	            return style.textContent || '';
	        }).join('\\n');
	        css += '\\n.wolfbench-export-root { display: flex !important; flex-direction: column !important; }';
	        css += '\\n.wolfbench-export-root .header { width: 100% !important; box-sizing: border-box !important; margin: 0 !important; padding: 22px 56px 12px !important; grid-template-columns: 72px auto max-content !important; justify-content: center !important; }';
	        css += '\\n.wolfbench-export-root .header h1 { white-space: nowrap !important; line-height: 1.05 !important; }';
	        css += '\\n.wolfbench-export-root .header-logo { object-fit: contain !important; }';
	        css += '\\n.wolfbench-export-root .header-logo-wandb { width: auto !important; height: 58px !important; max-height: 58px !important; margin-left: -11px !important; }';
	        css += '\\n.wolfbench-export-root .chart-wrapper { margin-bottom: 0 !important; }';
	        css += '\\n.wolfbench-export-root .chart-export-footer { display: flex !important; align-items: flex-start !important; justify-content: center !important; box-sizing: border-box !important; height: 48px !important; padding-top: 4px !important; color: #FFCC33 !important; font-weight: 800 !important; font-size: 22px !important; line-height: 1 !important; letter-spacing: 0 !important; }';
	        css += '\\n.wolfbench-export-root .chart-scroll { overflow: visible !important; padding-bottom: 0 !important; scrollbar-width: none !important; }';
	        css += '\\n.wolfbench-export-root .model-highlight-box { background: transparent !important; box-shadow: none !important; }';
        css += '\\n.wolfbench-export-root .agent-badge { display: inline-flex !important; align-items: center !important; justify-content: center !important; width: 40px !important; min-width: 40px !important; height: 40px !important; line-height: 0 !important; padding: 3px !important; border-radius: 999px !important; box-shadow: none !important; text-shadow: none !important; overflow: hidden !important; }';
        css += '\\n.wolfbench-export-root .agent-logo, .wolfbench-export-root .agent-logo svg, .wolfbench-export-root .agent-logo img { width: 32px !important; height: 32px !important; }';
        css += '\\n.wolfbench-export-root .three-bars-depth-label-layer { z-index: 12 !important; }';
        css += '\\n.wolfbench-export-root .chart-scroll::-webkit-scrollbar { display: none !important; }';
        css += '\\n.wolfbench-export-root * { animation: none !important; transition: none !important; }';
        return css.replace(/<\\/style/gi, '<\\\\/style');
	    }

	    function prepareExportAgentLogos(sourceRoot, cloneRoot) {
	        var sourceLogos = Array.prototype.slice.call(sourceRoot.querySelectorAll('.agent-logo'));
	        var cloneLogos = Array.prototype.slice.call(cloneRoot.querySelectorAll('.agent-logo'));
	        cloneLogos.forEach(function(cloneLogo, index) {
	            var sourceLogo = sourceLogos[index];
	            var sourceStyle = sourceLogo ? getComputedStyle(sourceLogo) : null;
	            var color = sourceStyle && sourceStyle.color ? sourceStyle.color : 'currentColor';
	            cloneLogo.style.color = color;
	            var img = cloneLogo.querySelector('img');
	            if (img) {
	                img.loading = 'eager';
	                img.decoding = 'sync';
	                img.style.display = 'block';
	                img.style.width = '100%';
	                img.style.height = '100%';
	                img.style.objectFit = 'contain';
	                return;
	            }
	            var svg = cloneLogo.querySelector('svg');
	            if (!svg) return;
	            var svgClone = svg.cloneNode(true);
	            svgClone.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
	            svgClone.setAttribute('width', '32');
	            svgClone.setAttribute('height', '32');
	            svgClone.style.width = '32px';
	            svgClone.style.height = '32px';
	            svgClone.style.display = 'block';
	            svgClone.style.color = color;
	            if (!cloneLogo.classList.contains('agent-logo-branded')) {
	                svgClone.setAttribute('fill', color);
	                Array.prototype.forEach.call(svgClone.querySelectorAll('*'), function(node) {
	                    node.setAttribute('fill', color);
	                    if (node.getAttribute('stroke') === 'currentColor') node.setAttribute('stroke', color);
	                    if (node.style) {
	                        node.style.fill = color;
	                        if (node.style.stroke === 'currentColor') node.style.stroke = color;
	                    }
	                });
	            }
	            var serialized = new XMLSerializer().serializeToString(svgClone);
	            var exportImg = document.createElement('img');
	            exportImg.alt = '';
	            exportImg.loading = 'eager';
	            exportImg.decoding = 'sync';
	            exportImg.src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(serialized);
	            exportImg.style.display = 'block';
	            exportImg.style.width = '100%';
	            exportImg.style.height = '100%';
	            exportImg.style.objectFit = 'contain';
	            svg.replaceWith(exportImg);
	        });
	    }

	    function waitForExportImages(root) {
	        var images = Array.prototype.slice.call(root.querySelectorAll('img'));
	        if (!images.length) return Promise.resolve();
	        return Promise.all(images.map(function(img) {
	            if (img.complete && img.naturalWidth !== 0) return Promise.resolve();
	            return new Promise(function(resolve) {
	                var done = function() {
	                    img.removeEventListener('load', done);
	                    img.removeEventListener('error', done);
	                    resolve();
	                };
	                img.addEventListener('load', done, {once: true});
	                img.addEventListener('error', done, {once: true});
	                setTimeout(done, 1500);
	            });
	        }));
	    }

	    function exportImageLoad(src) {
	        return new Promise(function(resolve) {
	            if (!src) {
	                resolve(null);
	                return;
	            }
	            var img = new Image();
	            var settled = false;
	            var finish = function(value) {
	                if (settled) return;
	                settled = true;
	                clearTimeout(timer);
	                resolve(value);
	            };
	            var timer = setTimeout(function() { finish(null); }, 1500);
	            img.onload = function() { finish(img); };
	            img.onerror = function() { finish(null); };
	            img.src = src;
	        });
	    }

	    function exportLogoImageSrc(sourceLogo) {
	        if (!sourceLogo) return '';
	        var existingImg = sourceLogo.querySelector('img');
	        if (existingImg && (existingImg.currentSrc || existingImg.src)) {
	            return existingImg.currentSrc || existingImg.src;
	        }
	        var svg = sourceLogo.querySelector('svg');
	        if (!svg) return '';
	        var color = getComputedStyle(sourceLogo).color || 'currentColor';
	        var svgClone = svg.cloneNode(true);
	        svgClone.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
	        svgClone.setAttribute('width', '32');
	        svgClone.setAttribute('height', '32');
	        svgClone.style.width = '32px';
	        svgClone.style.height = '32px';
	        svgClone.style.display = 'block';
	        svgClone.style.color = color;
	        if (!sourceLogo.classList.contains('agent-logo-branded')) {
	            svgClone.setAttribute('fill', color);
	            Array.prototype.forEach.call(svgClone.querySelectorAll('*'), function(node) {
	                node.setAttribute('fill', color);
	                if (node.getAttribute('stroke') === 'currentColor') node.setAttribute('stroke', color);
	                if (node.style) {
	                    node.style.fill = color;
	                    if (node.style.stroke === 'currentColor') node.style.stroke = color;
	                }
	            });
	        }
	        return 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(new XMLSerializer().serializeToString(svgClone));
	    }

	    async function rasterizeExportAgentBadges(sourceRoot, cloneRoot) {
	        if (!sourceRoot || !cloneRoot) return;
	        var sourceBadges = Array.prototype.slice.call(sourceRoot.querySelectorAll('.agent-badge'));
	        var cloneBadges = Array.prototype.slice.call(cloneRoot.querySelectorAll('.agent-badge'));
	        for (var i = 0; i < cloneBadges.length; i++) {
	            var sourceBadge = sourceBadges[i];
	            var cloneBadge = cloneBadges[i];
	            if (!sourceBadge || !cloneBadge) continue;
	            var sourceGroup = sourceBadge.closest('.model-group');
	            var sourceWrapper = sourceBadge.closest('.bar-wrapper');
	            if (sourceGroup && !elementVisible(sourceGroup)) continue;
	            if (sourceWrapper && (sourceWrapper.offsetParent === null || sourceWrapper.classList.contains('agent-hidden') || sourceWrapper.classList.contains('bar-dismissed'))) continue;
	            var sourceLogo = sourceBadge.querySelector('.agent-logo');
	            var badgeStyle = getComputedStyle(sourceBadge);
	            var logoImage = await exportImageLoad(exportLogoImageSrc(sourceLogo));
	            var size = Math.max(32, Math.round(sourceBadge.getBoundingClientRect().width || 40));
	            var scale = 3;
	            var canvas = document.createElement('canvas');
	            canvas.width = size * scale;
	            canvas.height = size * scale;
	            var ctx = canvas.getContext('2d');
	            if (!ctx) continue;
	            ctx.scale(scale, scale);
	            var center = size / 2;
	            var radius = size / 2 - 0.5;
	            ctx.clearRect(0, 0, size, size);
	            ctx.beginPath();
	            ctx.arc(center, center, radius, 0, Math.PI * 2);
	            ctx.closePath();
	            ctx.fillStyle = badgeStyle.backgroundColor || 'rgba(5,8,10,0.72)';
	            ctx.fill();
	            ctx.save();
	            ctx.beginPath();
	            ctx.arc(center, center, radius - 1, 0, Math.PI * 2);
	            ctx.clip();
	            if (logoImage) {
	                var logoSize = Math.max(1, size - 8);
	                ctx.drawImage(logoImage, (size - logoSize) / 2, (size - logoSize) / 2, logoSize, logoSize);
	            }
	            ctx.restore();
	            ctx.lineWidth = 1;
	            ctx.strokeStyle = badgeStyle.borderColor || 'rgba(255,255,255,0.16)';
	            ctx.beginPath();
	            ctx.arc(center, center, radius, 0, Math.PI * 2);
	            ctx.stroke();
	            var badgeImg = document.createElement('img');
	            badgeImg.alt = '';
	            badgeImg.loading = 'eager';
	            badgeImg.decoding = 'sync';
	            badgeImg.src = canvas.toDataURL('image/png');
	            badgeImg.style.display = 'block';
	            badgeImg.style.width = size + 'px';
	            badgeImg.style.height = size + 'px';
	            badgeImg.style.pointerEvents = 'none';
	            cloneBadge.replaceChildren(badgeImg);
	            cloneBadge.style.width = size + 'px';
	            cloneBadge.style.minWidth = size + 'px';
	            cloneBadge.style.height = size + 'px';
	            cloneBadge.style.padding = '0';
	            cloneBadge.style.border = '0';
	            cloneBadge.style.background = 'transparent';
	            cloneBadge.style.overflow = 'visible';
	        }
	    }

    function clampExportByte(value) {
        return Math.max(0, Math.min(255, Math.round(value)));
    }

    function exportHexToRgb(hex) {
        var raw = (hex || '').replace('#', '').trim();
        if (raw.length === 3) raw = raw.replace(/(.)/g, '$1$1');
        if (!/^[0-9a-f]{6}$/i.test(raw)) return null;
        return {
            r: parseInt(raw.slice(0, 2), 16),
            g: parseInt(raw.slice(2, 4), 16),
            b: parseInt(raw.slice(4, 6), 16)
        };
    }

    function exportRgbToHex(rgb) {
        function part(value) {
            return clampExportByte(value).toString(16).padStart(2, '0');
        }
        return '#' + part(rgb.r) + part(rgb.g) + part(rgb.b);
    }

    function exportEnhanceRgb(rgb) {
        var avg = (rgb.r + rgb.g + rgb.b) / 3;
        var saturation = 1.36;
        var contrast = 1.14;
        var brightness = 1.035;
        return {
            r: clampExportByte((avg + (rgb.r - avg) * saturation - 128) * contrast + 128 * brightness),
            g: clampExportByte((avg + (rgb.g - avg) * saturation - 128) * contrast + 128 * brightness),
            b: clampExportByte((avg + (rgb.b - avg) * saturation - 128) * contrast + 128 * brightness)
        };
    }

    function exportEnhanceGradient(value) {
        return (value || '').replace(/#([0-9a-f]{3}|[0-9a-f]{6})\\b/gi, function(match) {
            var rgb = exportHexToRgb(match);
            return rgb ? exportRgbToHex(exportEnhanceRgb(rgb)) : match;
        });
    }

    function exportGradientStops(value) {
        var matches = [];
        var regex = /(#[0-9a-f]{3}\\b|#[0-9a-f]{6}\\b|rgba?\\([^)]*\\))\\s*(\\d+(?:\\.\\d+)?)?%?/gi;
        var match;
        while ((match = regex.exec(value || ''))) {
            matches.push({
                color: match[1],
                stop: match[2] == null ? null : Math.max(0, Math.min(100, parseFloat(match[2]))) / 100
            });
        }
        if (!matches.length) return null;
        if (matches.length === 1) matches[0].stop = 0;
        for (var i = 0; i < matches.length; i++) {
            if (matches[i].stop == null) matches[i].stop = matches.length === 1 ? 0 : i / (matches.length - 1);
        }
        return matches;
    }

    function exportUsableColor(value, fallback) {
        var color = (value || '').trim();
        if (!color || color === 'transparent' || /^rgba?\\(\\s*0\\s*,\\s*0\\s*,\\s*0\\s*,\\s*0\\s*\\)$/i.test(color)) {
            return fallback || '#27ae60';
        }
        return color;
    }

    function exportFirstRgba(value) {
        var match = String(value || '').match(/rgba?\\(\\s*([\\d.]+)\\s*,\\s*([\\d.]+)\\s*,\\s*([\\d.]+)(?:\\s*,\\s*([\\d.]+))?\\s*\\)/i);
        if (!match) return null;
        return {
            r: clampExportByte(parseFloat(match[1])),
            g: clampExportByte(parseFloat(match[2])),
            b: clampExportByte(parseFloat(match[3])),
            a: match[4] == null ? 1 : Math.max(0, Math.min(1, parseFloat(match[4])))
        };
    }

    function exportRgbaString(color, alphaScale) {
        if (!color) return 'rgba(255,255,255,0)';
        var alpha = Math.max(0, Math.min(1, color.a * alphaScale));
        return 'rgba(' + color.r + ',' + color.g + ',' + color.b + ',' + alpha.toFixed(3) + ')';
    }

    function exportRoundedRectPath(ctx, x, y, width, height, tl, tr, br, bl) {
        tl = Math.max(0, Math.min(tl || 0, width / 2, height / 2));
        tr = Math.max(0, Math.min(tr || 0, width / 2, height / 2));
        br = Math.max(0, Math.min(br || 0, width / 2, height / 2));
        bl = Math.max(0, Math.min(bl || 0, width / 2, height / 2));
        ctx.beginPath();
        ctx.moveTo(x + tl, y);
        ctx.lineTo(x + width - tr, y);
        ctx.quadraticCurveTo(x + width, y, x + width, y + tr);
        ctx.lineTo(x + width, y + height - br);
        ctx.quadraticCurveTo(x + width, y + height, x + width - br, y + height);
        ctx.lineTo(x + bl, y + height);
        ctx.quadraticCurveTo(x, y + height, x, y + height - bl);
        ctx.lineTo(x, y + tl);
        ctx.quadraticCurveTo(x, y, x + tl, y);
        ctx.closePath();
    }

    function drawExportSegmentPolish(ctx, x, y, width, height, segment) {
        var segmentStyle = segment && segment.style ? segment.style : {};
        var glowColor = exportFirstRgba(segmentStyle.boxShadow);
        if (glowColor) {
            var glow = ctx.createRadialGradient(
                x + width * 0.58, y + height * 0.40, 0,
                x + width * 0.58, y + height * 0.40, Math.max(width, height) * 0.78
            );
            glow.addColorStop(0, exportRgbaString(glowColor, 0.17));
            glow.addColorStop(0.58, exportRgbaString(glowColor, 0.07));
            glow.addColorStop(1, exportRgbaString(glowColor, 0));
            ctx.fillStyle = glow;
            ctx.fillRect(x, y, width, height);
        }

        var shine = ctx.createLinearGradient(x + width * 0.12, y, x + width * 0.40, y);
        shine.addColorStop(0, 'rgba(255,255,255,0)');
        shine.addColorStop(0.52, 'rgba(255,255,255,0.13)');
        shine.addColorStop(1, 'rgba(255,255,255,0)');
        ctx.fillStyle = shine;
        ctx.fillRect(x + width * 0.12, y, width * 0.28, height);

        var edge = ctx.createLinearGradient(x, y, x + width, y);
        edge.addColorStop(0, 'rgba(255,255,255,0.045)');
        edge.addColorStop(0.12, 'rgba(255,255,255,0.010)');
        edge.addColorStop(0.74, 'rgba(0,0,0,0.000)');
        edge.addColorStop(1, 'rgba(0,0,0,0.115)');
        ctx.fillStyle = edge;
        ctx.fillRect(x, y, width, height);

        ctx.fillStyle = 'rgba(255,255,255,0.15)';
        ctx.fillRect(x, y, width, 1);
        ctx.fillStyle = 'rgba(0,0,0,0.20)';
        ctx.fillRect(x, y + height - 1, width, 1);
    }

    function exportActiveMetricFilter(chartArea) {
        var candidates = ['solid', 'worst', 'average', 'best', 'ceiling'];
        var metric = window._filterMetric || '';
        if (chartArea && chartArea.classList) {
            candidates.forEach(function(key) {
                if (!metric && chartArea.classList.contains('metric-filter-' + key)) metric = key;
            });
        }
        return candidates.indexOf(metric) >= 0 ? metric : null;
    }

    function exportMetricHeight(inner, metric) {
        var attr = metric ? 'data-h-' + metric : 'data-h-pct';
        var height = parseFloat(inner.getAttribute(attr) || '0');
        if (!height) height = parseFloat(inner.style.height || inner.getAttribute('data-h-pct') || '0');
        return height;
    }

    function exportMetricPaintSegment(segments, metric) {
        if (!metric) return null;
        if (metric === 'worst') {
            return segments.querySelector('.segment-solid') ||
                segments.querySelector('.segment-worst') ||
                segments.querySelector('.segment');
        }
        return segments.querySelector('.segment-' + metric) ||
            segments.querySelector('.segment-solid') ||
            segments.querySelector('.segment');
    }

    function paintExportSegment(ctx, x, y, width, height, segment) {
        var segmentStyle = segment && segment.style ? segment.style : {};
        var background = segmentStyle.background || segmentStyle.backgroundImage || '';
        var stops = exportGradientStops(background);
        if (stops && stops.length) {
            var gradient = ctx.createLinearGradient(0, y, width, y + height);
            stops.forEach(function(stop) {
                gradient.addColorStop(stop.stop, stop.color);
            });
            ctx.fillStyle = gradient;
        } else {
            ctx.fillStyle = exportUsableColor(segmentStyle.backgroundColor, '#27ae60');
        }
        ctx.fillRect(x, y, width, height);
        drawExportSegmentPolish(ctx, x, y, width, height, segment);
    }

    function rasterizeExportBarSegments(cloneRoot) {
        var chartArea = cloneRoot.querySelector('.chart-area');
        if (chartArea && chartArea.classList.contains('token-depth-3d')) return false;
        var activeMetric = exportActiveMetricFilter(chartArea);
        var replaced = false;
        Array.prototype.forEach.call(cloneRoot.querySelectorAll('.bar-segments'), function(segments) {
            var inner = segments.closest('.bar-inner');
            var bar = segments.closest('.bar');
            if (!inner || !bar) return;
            var cssWidth = parseFloat(bar.style.width || bar.getAttribute('data-width') || '0');
            var cssHeight = activeMetric ?
                exportMetricHeight(inner, activeMetric) :
                parseFloat(inner.style.height || inner.getAttribute('data-h-pct') || '0');
            if (!cssWidth || !cssHeight) return;

            var scale = 3;
            var canvas = document.createElement('canvas');
            canvas.width = Math.ceil(cssWidth * scale);
            canvas.height = Math.ceil(cssHeight * scale);
            var ctx = canvas.getContext('2d');
            if (!ctx) return;
            ctx.scale(scale, scale);
            ctx.clearRect(0, 0, cssWidth, cssHeight);
            exportRoundedRectPath(ctx, 0, 0, cssWidth, cssHeight, 8, 8, 4, 4);
            ctx.clip();

            if (activeMetric) {
                paintExportSegment(ctx, 0, 0, cssWidth, cssHeight, exportMetricPaintSegment(segments, activeMetric));
            } else {
            var y = 0;
            var items = Array.prototype.slice.call(segments.querySelectorAll('.segment'));
            items.forEach(function(segment, index) {
                var segmentHeight = parseFloat(segment.style.height || segment.getAttribute('data-h-pct') || '0');
                if (!segmentHeight) return;
                if (index === items.length - 1) {
                    segmentHeight = Math.max(0, cssHeight - y);
                }
                paintExportSegment(ctx, 0, y, cssWidth, segmentHeight, segment);

                if (index < items.length - 1) {
                    ctx.fillStyle = 'rgba(0,0,0,0.22)';
                    ctx.fillRect(0, y + segmentHeight - 1, cssWidth, 1);
                }
                y += segmentHeight;
            });
            }

            var img = document.createElement('img');
            img.className = 'bar-segments-raster';
            img.src = canvas.toDataURL('image/png');
            img.width = canvas.width;
            img.height = canvas.height;
            img.style.display = 'block';
            img.style.width = '100%';
            img.style.height = activeMetric ? cssHeight + 'px' : '100%';
            if (activeMetric) {
                img.style.position = 'absolute';
                img.style.left = '0';
                img.style.right = '0';
                img.style.bottom = '0';
            }
            img.style.borderRadius = '8px 8px 4px 4px';
            img.style.pointerEvents = 'none';
            segments.replaceWith(img);
            replaced = true;
        });
        return replaced;
    }

    function prepareExportBarPaint(cloneRoot) {
        var chartArea = cloneRoot.querySelector('.chart-area');
        if (chartArea && chartArea.classList.contains('token-depth-3d')) {
            Array.prototype.forEach.call(cloneRoot.querySelectorAll('.bar-segments'), function(segments) {
                segments.style.opacity = '0';
                segments.style.background = 'transparent';
                segments.style.boxShadow = 'none';
            });
            return;
        }
        if (rasterizeExportBarSegments(cloneRoot)) return;
        Array.prototype.forEach.call(cloneRoot.querySelectorAll('.bar-segments'), function(segments) {
            segments.style.opacity = '1';
            segments.style.filter = 'none';
        });
        Array.prototype.forEach.call(cloneRoot.querySelectorAll('.segment'), function(segment) {
            var background = segment.style.background || segment.style.backgroundImage || '';
            var enhanced = exportEnhanceGradient(background);
            if (enhanced && enhanced !== background) segment.style.background = enhanced;
        });
        Array.prototype.forEach.call(cloneRoot.querySelectorAll('.segment-shine'), function(shine) {
            shine.remove();
        });
    }

    function replaceCanvasPixels(sourceRoot, cloneRoot) {
        var sourceCanvases = sourceRoot.querySelectorAll('canvas');
        var cloneCanvases = cloneRoot.querySelectorAll('canvas');
        Array.prototype.forEach.call(cloneCanvases, function(cloneCanvas, index) {
            var sourceCanvas = sourceCanvases[index];
            if (!sourceCanvas) return;
            try {
                var rect = sourceCanvas.getBoundingClientRect();
                var img = document.createElement('img');
                img.className = sourceCanvas.className;
                img.src = sourceCanvas.toDataURL('image/png');
                img.style.cssText = sourceCanvas.getAttribute('style') || '';
                img.style.position = 'absolute';
                img.style.left = sourceCanvas.style.left || '0px';
                img.style.top = sourceCanvas.style.top || '0px';
                img.style.width = (sourceCanvas.style.width || Math.ceil(rect.width) + 'px');
                img.style.height = (sourceCanvas.style.height || Math.ceil(rect.height) + 'px');
                img.style.pointerEvents = 'none';
                cloneCanvas.replaceWith(img);
            } catch (err) {
                cloneCanvas.remove();
            }
        });
    }

    function buildFullChartExportNode() {
        var wrapper = document.querySelector('.chart-wrapper');
        if (!wrapper) throw new Error('Chart not found.');
        var yAxis = wrapper.querySelector('.y-axis');
        var chartScroll = wrapper.querySelector('.chart-scroll');
        var chartArea = wrapper.querySelector('.chart-area');
        if (!yAxis || !chartScroll || !chartArea) throw new Error('Chart layout not found.');

        var yAxisWidth = Math.ceil(yAxis.getBoundingClientRect().width);
        var pageHeader = document.querySelector('.header');
        var headerHeight = pageHeader ? Math.ceil(pageHeader.getBoundingClientRect().height) + 34 : 0;
        var footerHeight = 48;
        var chartAreaStyle = getComputedStyle(chartArea);
        var chartScrollStyle = getComputedStyle(chartScroll);
        var modelsRow = chartArea.querySelector('.models-row');
        var contentWidth = visibleChartContentWidth(chartArea, modelsRow);
        var contentBottom = visibleChartContentBottom(chartArea, modelsRow);
        var fallbackAreaWidth = Math.ceil(Math.max(
            modelsRow ? modelsRow.scrollWidth : 0,
            numericPx(chartAreaStyle.minWidth),
            chartArea.scrollWidth || 0
        ));
        var areaWidth = Math.ceil(Math.max(
            contentWidth || fallbackAreaWidth,
            320
        ));
        var areaHeight = Math.ceil(Math.max(chartArea.scrollHeight, chartArea.getBoundingClientRect().height));
        var padTop = numericPx(chartScrollStyle.paddingTop);
        var padBottom = numericPx(chartScrollStyle.paddingBottom);
        var chartWidth = yAxisWidth + areaWidth;
        var exportWidth = Math.max(chartWidth, headerMinExportWidth(pageHeader));
        var chartBottomGap = Math.max(8, Math.min(20, padBottom ? padBottom * 0.28 : 10));
        var chartHeight = Math.ceil(padTop + Math.max(areaHeight, contentBottom) + chartBottomGap);
        var exportHeight = headerHeight + chartHeight + footerHeight;

        var exportRoot = document.createElement('div');
        exportRoot.className = 'wolfbench-export-root';
        exportRoot.style.width = exportWidth + 'px';
        exportRoot.style.height = exportHeight + 'px';
        exportRoot.style.background = '#1A1C1F';
        exportRoot.style.color = '#e6edf3';
        exportRoot.style.overflow = 'hidden';

        if (pageHeader) {
            var cloneHeader = pageHeader.cloneNode(true);
            exportRoot.appendChild(cloneHeader);
        }

	        var cloneWrapper = wrapper.cloneNode(true);
	        exportRoot.appendChild(cloneWrapper);
	        replaceCanvasPixels(wrapper, cloneWrapper);
	        prepareExportAgentLogos(wrapper, cloneWrapper);
	        prepareExportBarPaint(cloneWrapper);

        var cloneYAxis = cloneWrapper.querySelector('.y-axis');
        var cloneScroll = cloneWrapper.querySelector('.chart-scroll');
        var cloneArea = cloneWrapper.querySelector('.chart-area');
        cloneWrapper.style.width = chartWidth + 'px';
        cloneWrapper.style.height = chartHeight + 'px';
        cloneWrapper.style.marginBottom = '0';
        cloneWrapper.style.alignSelf = 'center';
        cloneWrapper.style.alignItems = 'flex-start';
        if (cloneYAxis) {
            cloneYAxis.style.width = yAxisWidth + 'px';
            cloneYAxis.style.flex = '0 0 ' + yAxisWidth + 'px';
        }
        if (cloneScroll) {
            cloneScroll.scrollLeft = 0;
            cloneScroll.style.flex = '0 0 ' + areaWidth + 'px';
            cloneScroll.style.width = areaWidth + 'px';
            cloneScroll.style.minWidth = areaWidth + 'px';
            cloneScroll.style.overflow = 'visible';
            cloneScroll.style.paddingBottom = '0';
        }
        if (cloneArea) {
            cloneArea.style.width = areaWidth + 'px';
            cloneArea.style.minWidth = areaWidth + 'px';
        }

        var exportFooter = document.createElement('div');
        exportFooter.className = 'chart-export-footer';
        exportFooter.textContent = 'wolfbench.ai';
        exportRoot.appendChild(exportFooter);

        exportRoot.insertAdjacentHTML('afterbegin', '<style>' + exportCssText() + '</style>');
        return {node: exportRoot, width: exportWidth, height: exportHeight};
    }

    async function refreshThreeBarsForExport() {
        if (!(window.WolfBenchThreeBars && window._tokenDepthEnabled)) return;
        var chartArea = document.querySelector('.chart-area');
        if (window.WolfBenchThreeBars.renderNow) {
            window.WolfBenchThreeBars.renderNow();
        } else {
            window.WolfBenchThreeBars.render();
        }
        for (var i = 0; i < 12; i++) {
            await nextFrame();
            if (!chartArea || chartArea.classList.contains('three-bars-ready')) return;
        }
    }

    async function renderFullChartPngBlob() {
        await refreshThreeBarsForExport();
        if (document.fonts && document.fonts.ready) {
            try { await document.fonts.ready; } catch (err) {}
        }
        await nextFrame();
        await nextFrame();
        var renderChart = await loadHtml2Canvas();
        var exported = buildFullChartExportNode();
        var renderScale = chartExportRenderScale(exported.width, exported.height);
        window.WolfBenchLastChartExport = {width: exported.width, height: exported.height, scale: renderScale};
        var host = document.createElement('div');
        host.style.position = 'absolute';
        host.style.left = '-' + (exported.width + 10000) + 'px';
        host.style.top = '0';
        host.style.width = exported.width + 'px';
        host.style.height = exported.height + 'px';
        host.style.overflow = 'hidden';
        host.style.pointerEvents = 'none';
        host.style.zIndex = '-1';
	        host.appendChild(exported.node);
	        document.body.appendChild(host);
	        try {
	            await rasterizeExportAgentBadges(document.querySelector('.chart-wrapper'), exported.node.querySelector('.chart-wrapper'));
	            await waitForExportImages(exported.node);
	            await nextFrame();
	            var canvas = await renderChart(exported.node, {
                backgroundColor: '#1A1C1F',
                scale: renderScale,
                useCORS: true,
                logging: false,
                width: exported.width,
                height: exported.height,
                windowWidth: exported.width,
                windowHeight: exported.height,
                scrollX: 0,
                scrollY: 0
            });
            return canvasToBlob(canvas);
        } finally {
            host.remove();
        }
    }

    function clipboardPngSupported() {
        if (!navigator.clipboard || !navigator.clipboard.write || !window.ClipboardItem) return false;
        if (typeof window.ClipboardItem.supports === 'function') return window.ClipboardItem.supports('image/png');
        return true;
    }

    async function copyChartScreenshotToClipboard(blob) {
        if (!clipboardPngSupported()) {
            throw new Error('Clipboard image copy is not available in this browser context.');
        }
        await navigator.clipboard.write([
            new ClipboardItem({'image/png': blob})
        ]);
    }

    function downloadChartScreenshot(blob) {
        var url = URL.createObjectURL(blob);
        var link = document.createElement('a');
        link.href = url;
        link.download = chartExportFilename();
        document.body.appendChild(link);
        link.click();
        link.remove();
        setTimeout(function() { URL.revokeObjectURL(url); }, 5000);
    }

    async function saveAndCopyChartScreenshot() {
        var blob = await renderFullChartPngBlob();
        var clipboardError = null;
        try {
            await copyChartScreenshotToClipboard(blob);
        } catch (err) {
            clipboardError = err;
        }
        downloadChartScreenshot(blob);
        return {copied: !clipboardError, clipboardError: clipboardError};
    }

    async function handleSave(event) {
        if (event) {
            event.preventDefault();
            event.stopPropagation();
        }
        setButtonState(saveButton, 'copying', '...', 'Saving and copying full chart PNG...');
        try {
            var result = await saveAndCopyChartScreenshot();
            if (result.copied) {
                setButtonState(saveButton, 'saved', '\\u2713', 'Saved full chart PNG and copied it to clipboard');
            } else {
                var msg = result.clipboardError && result.clipboardError.message
                    ? result.clipboardError.message
                    : 'Clipboard copy failed.';
                setButtonState(saveButton, 'partial', '\\u2193', 'Saved PNG, but did not copy it: ' + msg);
            }
        } catch (err) {
            console.error(err);
            setButtonState(saveButton, 'failed', '!', err && err.message ? err.message : 'Could not save or copy chart PNG');
        }
    }

    function addActivation(button, handler) {
        if (!button) return;
        rememberButtonDefaults(button);
        button.addEventListener('click', handler);
        button.addEventListener('keydown', function(event) {
            if (event.key === 'Enter' || event.key === ' ' || event.key === 'Spacebar') {
                handler(event);
            }
        });
    }

    addActivation(saveButton, handleSave);
})();"""

    table_sort_js = """(function() {
    var table = document.querySelector('.runs-table');
    if (!table) return;
    var thead = table.tHead;
    var tbody = table.tBodies[0];
    if (!thead || !tbody) return;
    var headers = thead.rows[0].cells;
    // Initial state: Date column (0) descending — matches Python sort order
    var sortCol = 0;
    var sortAsc = false;
    var urlState = window.WolfBenchUrlState ? window.WolfBenchUrlState.state : {};
    function notifyUrlChange() {
        if (window.WolfBenchUrlState) window.WolfBenchUrlState.notifyChange();
    }

    function parseVal(text, cell) {
        var explicit = cell ? cell.getAttribute('data-sort-value') : null;
        if (explicit !== null && explicit !== '') {
            var explicitNumber = Number(explicit);
            if (Number.isFinite(explicitNumber)) return explicitNumber;
        }
        var s = text.replace(/\\u00a0/g, ' ').trim();
        if (!s || s === '-' || s === '?') return null;
        s = s.replace(/^\\$/, '').replace(/,/g, '').replace(/\\s+/g, '').replace(/[%s]$/, '');
        var m = s.match(/^([\\d.]+)([KMB])$/i);
        if (m) {
            var n = parseFloat(m[1]);
            var suffix = m[2].toUpperCase();
            return suffix === 'B' ? n * 1e9 : suffix === 'M' ? n * 1e6 : n * 1e3;
        }
        m = s.match(/^(\\d+)h(\\d+)m$/);
        if (m) return parseInt(m[1]) * 60 + parseInt(m[2]);
        // Only treat as number if the ENTIRE string is numeric
        // (avoids parseFloat("2026-03-01 13:43") → 2026)
        if (/^-?\\d+(\\.\\d+)?$/.test(s)) return parseFloat(s);
        return null;
    }

    function cmp(a, b, col) {
        var at = a.cells[col].textContent.trim();
        var bt = b.cells[col].textContent.trim();
        var an = parseVal(at, a.cells[col]);
        var bn = parseVal(bt, b.cells[col]);
        if (an !== null || bn !== null) {
            if (an === null) return sortAsc ? 1 : -1;
            if (bn === null) return sortAsc ? -1 : 1;
            return an - bn;
        }
        return at.toLowerCase().localeCompare(bt.toLowerCase());
    }

    function applyTableSort(col, asc) {
        if (col < 0 || col >= headers.length) return;
        sortCol = col;
        sortAsc = asc;
        for (var j = 0; j < headers.length; j++) {
            headers[j].removeAttribute('data-sort');
        }
        headers[col].setAttribute('data-sort', sortAsc ? 'asc' : 'desc');
        var rows = Array.prototype.slice.call(tbody.rows);
        rows.sort(function(a, b) {
            var r = cmp(a, b, col);
            return sortAsc ? r : -r;
        });
        rows.forEach(function(row) { tbody.appendChild(row); });
        notifyUrlChange();
    }

    for (var i = 0; i < headers.length; i++) {
        (function(col) {
            headers[col].style.cursor = 'pointer';
            headers[col].addEventListener('click', function() {
                if (sortCol === col) {
                    sortAsc = !sortAsc;
                } else {
                    sortCol = col;
                    sortAsc = true;
                }
                applyTableSort(sortCol, sortAsc);
            });
        })(i);
    }
    if (urlState.runSort) {
        applyTableSort(urlState.runSort.col, urlState.runSort.dir === 'asc');
    }
})();"""

    model_toggle_js = """(function() {
    var activeModels = {};
    var modelBtns = document.querySelectorAll('.model-btn');
    var modelGroups = document.querySelectorAll('.model-group');
    var modelsRow = document.querySelector('.models-row');
    var modelBar = document.querySelector('.model-bar');
    var chartArea = document.querySelector('.chart-area');
    var dragSrc = null;
    var urlState = window.WolfBenchUrlState ? window.WolfBenchUrlState.state : {};
    var modelOrderUserSet = false;
    function notifyUrlChange() {
        if (window.WolfBenchUrlState) window.WolfBenchUrlState.notifyChange();
    }

    // Collect all model IDs and init with all active
    var allModelIds = [];
    modelBtns.forEach(function(b) { var m = b.getAttribute('data-model'); if (m) { allModelIds.push(m); activeModels[m] = true; } });
    if (urlState.models) {
        var initialModels = {};
        urlState.models.forEach(function(m) {
            if (allModelIds.indexOf(m) !== -1) initialModels[m] = true;
        });
        if (urlState.models.length === 0 || Object.keys(initialModels).length > 0) {
            activeModels = initialModels;
        }
    }

    function currentModelOrder() {
        return Array.prototype.slice.call(modelBar.querySelectorAll('.model-btn')).map(function(b) {
            return b.getAttribute('data-model');
        });
    }

    function applyModelOrder(order) {
        if (!modelBar || !modelsRow || !order || !order.length) return;
        var btnMap = {};
        Array.prototype.slice.call(modelBar.querySelectorAll('.model-btn')).forEach(function(b) {
            btnMap[b.getAttribute('data-model')] = b;
        });
        order.forEach(function(m) {
            if (btnMap[m]) modelBar.appendChild(btnMap[m]);
        });
        allModelIds.forEach(function(m) {
            if (order.indexOf(m) === -1 && btnMap[m]) modelBar.appendChild(btnMap[m]);
        });
        Array.prototype.slice.call(modelBar.querySelectorAll('.model-btn')).forEach(function(b) {
            var group = modelsRow.querySelector('.model-group[data-model="' + b.getAttribute('data-model') + '"]');
            if (group) modelsRow.appendChild(group);
        });
        modelOrderUserSet = true;
    }

    applyModelOrder(urlState.modelOrder);
    window._getModelOrderForUrl = function() {
        return modelOrderUserSet ? currentModelOrder() : null;
    };

    // Recalculate chart min-width based on visible model groups
    window.updateChartWidth = function() {
        if (!chartArea) return;
        var filtered = modelsRow && modelsRow.classList.contains('agent-filtered');
        var totalW = 0, n = 0;
        modelGroups.forEach(function(g) {
            if (g.classList.contains('model-hidden') || g.classList.contains('model-hidden-user') || g.classList.contains('metric-hidden')) return;
            if (filtered) {
                // Compute actual visible bar widths (agent-hidden bars are display:none)
                var visibleBars = g.querySelectorAll('.bar-wrapper:not(.agent-hidden)');
                if (visibleBars.length === 0) return;
                var gw = 0;
                visibleBars.forEach(function(bw) {
                    var bar = bw.querySelector('.bar');
                    if (bar) gw += parseInt(bar.style.width) || 0;
                });
                if (visibleBars.length > 1) gw += (visibleBars.length - 1) * 8;
                totalW += gw;
            } else {
                totalW += parseInt(g.getAttribute('data-width')) || 0;
            }
            n++;
        });
        if (n > 0) {
            var gap = 68;
            totalW += (n - 1) * gap + 2 * 48;
        }
        chartArea.style.minWidth = (n > 0 ? totalW : 0) + 'px';
        if (window.adjustLabelPadding) window.adjustLabelPadding();
    };

    // Apply model filter state to DOM
    function applyModelFilter() {
        var nActive = Object.keys(activeModels).length;
        var allActive = nActive === allModelIds.length;
        modelBtns.forEach(function(btn) {
            var m = btn.getAttribute('data-model');
            btn.classList.toggle('dimmed', !allActive && !activeModels[m]);
        });
	        modelGroups.forEach(function(g) {
	            g.classList.toggle('model-hidden-user', !allActive && !activeModels[g.getAttribute('data-model')]);
	        });
	        if (window.WolfBenchClearHiddenModelHighlights) window.WolfBenchClearHiddenModelHighlights();
	        syncVisToggle();
        if (window.applyAgentFilter) {
            window.applyAgentFilter();
        } else {
            window.updateChartWidth();
            if (window.filterRunsTable) window.filterRunsTable();
        }
    }

    // Toggle visibility
    modelBtns.forEach(function(btn) {
        btn.addEventListener('click', function(e) {
            if (btn.getAttribute('data-just-dragged') === 'true') {
                btn.removeAttribute('data-just-dragged');
                return;
            }
            var model = btn.getAttribute('data-model');
            if (!model) return;

            var _lp = window._longPressed; window._longPressed = false;
            if (e.ctrlKey || e.metaKey || e.shiftKey || _lp) {
                // Long-press / modifier: toggle this model, so selected models can be
                // quickly removed from the current all-model view.
                if (activeModels[model]) {
                    delete activeModels[model];
                } else {
                    activeModels[model] = true;
                }
                // None active → all active
                if (Object.keys(activeModels).length === 0) {
                    allModelIds.forEach(function(m) { activeModels[m] = true; });
                }
            } else {
                // Default all-visible state: clicking a model focuses it.
                // Once filtered, normal clicks keep acting as visibility toggles.
                if (Object.keys(activeModels).length === allModelIds.length) {
                    activeModels = {};
                    activeModels[model] = true;
                } else {
                    if (activeModels[model]) {
                        delete activeModels[model];
                    } else {
                        activeModels[model] = true;
                    }
                    // None active → all active
                    if (Object.keys(activeModels).length === 0) {
                        allModelIds.forEach(function(m) { activeModels[m] = true; });
                    }
                }
            }
            applyModelFilter();
            notifyUrlChange();
        });
    });

    // Drag to reorder
    modelBtns.forEach(function(btn) {
        btn.addEventListener('dragstart', function(e) {
            if (btn.classList.contains('unavailable') || btn.getAttribute('draggable') === 'false') {
                e.preventDefault();
                return;
            }
            dragSrc = btn;
            btn.classList.add('dragging');
            e.dataTransfer.effectAllowed = 'move';
            e.dataTransfer.setData('text/plain', btn.getAttribute('data-model'));
        });
        btn.addEventListener('dragend', function() {
            btn.classList.remove('dragging');
            btn.setAttribute('data-just-dragged', 'true');
            setTimeout(function() { btn.removeAttribute('data-just-dragged'); }, 50);
            modelBtns.forEach(function(b) { b.classList.remove('drag-over'); });
            dragSrc = null;
        });
        btn.addEventListener('dragover', function(e) {
            if (!dragSrc || btn.classList.contains('unavailable')) return;
            e.preventDefault();
            e.dataTransfer.dropEffect = 'move';
            if (btn !== dragSrc) btn.classList.add('drag-over');
        });
        btn.addEventListener('dragleave', function() { btn.classList.remove('drag-over'); });
        btn.addEventListener('drop', function(e) {
            e.preventDefault();
            btn.classList.remove('drag-over');
            if (!dragSrc || dragSrc === btn || btn.classList.contains('unavailable')) return;
            var allBtns = Array.prototype.slice.call(modelBar.querySelectorAll('.model-btn'));
            var srcIdx = allBtns.indexOf(dragSrc);
            var tgtIdx = allBtns.indexOf(btn);
            if (srcIdx < tgtIdx) {
                modelBar.insertBefore(dragSrc, btn.nextSibling);
            } else {
                modelBar.insertBefore(dragSrc, btn);
            }
            // Reorder chart model groups to match button order
            Array.prototype.slice.call(modelBar.querySelectorAll('.model-btn')).forEach(function(b) {
                var group = modelsRow.querySelector('.model-group[data-model="' + b.getAttribute('data-model') + '"]');
                if (group) modelsRow.appendChild(group);
            });
            if (window.WolfBenchRefreshModelHighlights) window.WolfBenchRefreshModelHighlights();
            modelOrderUserSet = true;
            notifyUrlChange();
        });
    });

    // Show/hide all toggle (eye icon)
    var visToggle = document.getElementById('modelVisToggle');
    function syncVisToggle() {
        if (visToggle) visToggle.classList.toggle('dimmed', Object.keys(activeModels).length < allModelIds.length);
    }
    if (visToggle) {
        visToggle.addEventListener('click', function() {
            var allActive = Object.keys(activeModels).length === allModelIds.length;
            if (allActive) {
                // Hide all — special case: do NOT auto-reactivate
                activeModels = {};
            } else {
                // Show all
                activeModels = {};
                allModelIds.forEach(function(m) { activeModels[m] = true; });
            }
            applyModelFilter();
            notifyUrlChange();
        });
    }
    applyModelFilter();
})();"""

    model_highlight_js = """(function() {
    function isGroupHidden(group) {
        return group.classList.contains('model-hidden') ||
            group.classList.contains('model-hidden-user') ||
            group.classList.contains('metric-hidden');
    }

    function setHighlight(group, active) {
        var label = group.querySelector('.model-label');
        group.classList.toggle('model-highlighted', active);
        if (label) label.setAttribute('aria-pressed', active ? 'true' : 'false');
        if (window.adjustLabelPadding) {
            window.requestAnimationFrame(window.adjustLabelPadding);
        }
    }

    function refreshHighlightBounds(group) {
        var label = group.querySelector('.model-label');
        if (!label) return;
        var labelWidth = label.offsetWidth || 0;
        var labelHeight = label.offsetHeight || 24;
        var groupWidth = group.offsetWidth || 0;
        var xPad = Math.max(28, Math.ceil(Math.max(0, labelWidth - groupWidth) / 2 + 28));
        var leftPad = xPad;
        var rightPad = xPad;
        var chartArea = group.closest('.chart-area');
        if (chartArea && chartArea.classList.contains('token-depth-3d')) {
            var groupRectForDepth = group.getBoundingClientRect();
            var maxRight = groupRectForDepth.right;
            group.querySelectorAll('.bar-wrapper:not(.agent-hidden):not(.bar-dismissed)').forEach(function(wrapper) {
                if (wrapper.offsetParent === null) return;
                var inner = wrapper.querySelector('.bar-inner') || wrapper.querySelector('.bar');
                if (!inner) return;
                var rect = inner.getBoundingClientRect();
                var visualDepth = parseFloat(getComputedStyle(wrapper).getPropertyValue('--iso-visual-depth')) ||
                    parseFloat(wrapper.getAttribute('data-token-depth')) || 0;
                maxRight = Math.max(maxRight, rect.right + visualDepth + 12);
            });
            rightPad = Math.max(rightPad, Math.ceil(maxRight - groupRectForDepth.right + 28));
        }
        if (chartArea) {
            var contentEdges = chartContentEdges(chartArea);
            var groupRect = group.getBoundingClientRect();
            leftPad = Math.min(leftPad, Math.max(0, Math.floor(groupRect.left - contentEdges.left)));
            rightPad = Math.min(rightPad, Math.max(0, Math.floor(contentEdges.right - groupRect.right + 16)));
        }
        setHighlightPx(group, '--model-highlight-xpad', xPad);
        setHighlightPx(group, '--model-highlight-left-pad', leftPad);
        setHighlightPx(group, '--model-highlight-right-pad', rightPad);
        setHighlightPx(group, '--model-label-height', Math.ceil(labelHeight));
    }

    function chartContentEdges(chartArea) {
        var chartRect = chartArea.getBoundingClientRect();
        var left = chartRect.left;
        var right = chartRect.left + Math.max(
            chartRect.width || 0,
            chartArea.clientWidth || 0,
            chartArea.offsetWidth || 0,
            chartArea.scrollWidth || 0
        );
        var modelsRow = chartArea.querySelector('.models-row');
        if (modelsRow) {
            var rowRect = modelsRow.getBoundingClientRect();
            left = Math.min(left, rowRect.left);
            right = Math.max(right, rowRect.left + Math.max(
                rowRect.width || 0,
                modelsRow.clientWidth || 0,
                modelsRow.offsetWidth || 0,
                modelsRow.scrollWidth || 0
            ));
        }
        return {left: left, right: right};
    }

    function cssPx(group, name, fallback) {
        var value = getComputedStyle(group).getPropertyValue(name);
        var parsed = parseFloat(value);
        return isFinite(parsed) ? parsed : fallback;
    }

    function setHighlightPx(group, name, value) {
        var next = Math.max(0, Math.floor(value)) + 'px';
        if (group.style.getPropertyValue(name) !== next) {
            group.style.setProperty(name, next);
        }
    }

    function setSidePad(group, side, value) {
        setHighlightPx(group, '--model-highlight-' + side + '-pad', value);
    }

    function resolveHighlightCollisions(groups) {
        var cluster = [];
        function flushCluster() {
            if (cluster.length > 1) balanceHighlightCluster(cluster);
            cluster = [];
        }
        groups.forEach(function(group) {
            if (group.classList.contains('model-highlighted')) {
                cluster.push(group);
            } else {
                flushCluster();
            }
        });
        flushCluster();
    }

    function balanceHighlightCluster(cluster) {
        var minGap = 10;
        var target = Infinity;
        var collided = false;
        for (var i = 0; i < cluster.length; i++) {
            target = Math.min(target, cssPx(cluster[i], '--model-highlight-left-pad', 28));
            target = Math.min(target, cssPx(cluster[i], '--model-highlight-right-pad', 28));
        }
        for (var j = 0; j < cluster.length - 1; j++) {
            var left = cluster[j];
            var right = cluster[j + 1];
            var leftRect = left.getBoundingClientRect();
            var rightRect = right.getBoundingClientRect();
            var gap = Math.floor(rightRect.left - leftRect.right);
            var available = Math.max(0, gap - minGap);
            var leftPad = cssPx(left, '--model-highlight-right-pad', 28);
            var rightPad = cssPx(right, '--model-highlight-left-pad', 28);
            if (leftPad + rightPad > available) collided = true;
            target = Math.min(target, Math.floor(available / 2));
        }
        if (!collided || !isFinite(target)) return;
        target = Math.max(0, Math.floor(target));
        cluster.forEach(function(group) {
            setSidePad(group, 'left', target);
            setSidePad(group, 'right', target);
        });
    }

    window.WolfBenchRefreshModelHighlights = function() {
        var groups = Array.prototype.slice.call(document.querySelectorAll('.model-group'));
        groups.forEach(refreshHighlightBounds);
        resolveHighlightCollisions(groups.filter(function(group) {
            return !isGroupHidden(group);
        }));
    };

    window.WolfBenchClearHiddenModelHighlights = function() {
        document.querySelectorAll('.model-group.model-highlighted').forEach(function(group) {
            if (isGroupHidden(group)) setHighlight(group, false);
        });
    };

    document.querySelectorAll('.model-group').forEach(function(group) {
        var label = group.querySelector('.model-label');
        if (!label) return;
        refreshHighlightBounds(group);
        label.setAttribute('role', 'button');
        label.setAttribute('tabindex', '0');
        label.setAttribute('aria-pressed', group.classList.contains('model-highlighted') ? 'true' : 'false');
        label.setAttribute('title', 'Highlight this model');

        function toggleHighlight(event) {
            if (event) {
                event.preventDefault();
                event.stopPropagation();
            }
            refreshHighlightBounds(group);
            setHighlight(group, !group.classList.contains('model-highlighted'));
            window.WolfBenchRefreshModelHighlights();
        }

        label.addEventListener('click', toggleHighlight);
        label.addEventListener('keydown', function(event) {
            if (event.key === 'Enter' || event.key === ' ' || event.key === 'Spacebar') {
                toggleHighlight(event);
            }
        });
    });
    window.addEventListener('resize', window.WolfBenchRefreshModelHighlights);
    if (document.fonts && document.fonts.ready) {
        document.fonts.ready.then(window.WolfBenchRefreshModelHighlights);
    }
})();"""

    bar_drag_js = """(function() {
    var barDragSrc = null;
    var barDragRow = null;
    var barDropped = false;

    document.querySelectorAll('.bar-wrapper').forEach(function(wrapper) {
        wrapper.addEventListener('dragstart', function(e) {
            barDragSrc = wrapper;
            barDragRow = wrapper.parentElement;
            barDropped = false;
            wrapper.classList.add('bar-dragging');
            e.dataTransfer.effectAllowed = 'move';
            e.dataTransfer.setData('text/plain', 'bar');
        });
        wrapper.addEventListener('dragend', function() {
            wrapper.classList.remove('bar-dragging');
            if (barDragRow) {
                barDragRow.querySelectorAll('.bar-wrapper').forEach(function(w) {
                    w.classList.remove('bar-drag-over');
                });
            }
            // Dropped outside chart → hide this bar
            if (!barDropped && barDragSrc) {
                barDragSrc.classList.add('bar-dismissed');
                barDragSrc.style.display = 'none';
                // Hide model group if all bars dismissed/hidden
                var group = barDragSrc.closest('.model-group');
                if (group) {
                    var anyVisible = group.querySelector('.bar-wrapper:not(.bar-dismissed):not(.agent-hidden)');
                    if (!anyVisible) group.classList.add('model-hidden');
                }
                if (window.updateChartWidth) window.updateChartWidth();
                if (window.syncAgentAvailability) window.syncAgentAvailability();
                if (window.filterRunsTable) window.filterRunsTable();
            }
            barDragSrc = null;
            barDragRow = null;
        });
        wrapper.addEventListener('dragover', function(e) {
            if (!barDragSrc || wrapper.parentElement !== barDragRow) return;
            e.preventDefault();
            e.stopPropagation();
            e.dataTransfer.dropEffect = 'move';
            if (wrapper !== barDragSrc) wrapper.classList.add('bar-drag-over');
        });
        wrapper.addEventListener('dragleave', function() {
            wrapper.classList.remove('bar-drag-over');
        });
        wrapper.addEventListener('drop', function(e) {
            if (!barDragSrc || wrapper.parentElement !== barDragRow) return;
            e.preventDefault();
            e.stopPropagation();
            barDropped = true;
            wrapper.classList.remove('bar-drag-over');
            if (barDragSrc === wrapper) return;
            var siblings = Array.prototype.slice.call(barDragRow.querySelectorAll('.bar-wrapper'));
            var srcIdx = siblings.indexOf(barDragSrc);
            var tgtIdx = siblings.indexOf(wrapper);
            if (srcIdx < tgtIdx) {
                barDragRow.insertBefore(barDragSrc, wrapper.nextSibling);
            } else {
                barDragRow.insertBefore(barDragSrc, wrapper);
            }
        });
    });

    // Chart area is a valid drop zone (prevents accidental dismiss when dragging within chart)
    var chartScroll = document.querySelector('.chart-scroll');
    if (chartScroll) {
        chartScroll.addEventListener('dragover', function(e) {
            if (!barDragSrc) return;
            e.preventDefault();
            e.dataTransfer.dropEffect = 'move';
        });
        chartScroll.addEventListener('drop', function(e) {
            if (!barDragSrc) return;
            e.preventDefault();
            barDropped = true;
        });
    }

    // Restore all dismissed bars via sort toggle button
    var sortToggle = document.getElementById('barSortToggle');
    if (sortToggle) {
        sortToggle.addEventListener('click', function() {
            document.querySelectorAll('.bar-wrapper.bar-dismissed').forEach(function(w) {
                w.classList.remove('bar-dismissed');
                if (!w.classList.contains('agent-hidden')) w.style.display = '';
            });
            document.querySelectorAll('.model-group').forEach(function(g) {
                var anyVisible = g.querySelector('.bar-wrapper:not(.bar-dismissed):not(.agent-hidden)');
                if (anyVisible) g.classList.remove('model-hidden');
            });
            if (window.updateChartWidth) window.updateChartWidth();
            if (window.syncAgentAvailability) window.syncAgentAvailability();
            if (window.filterRunsTable) window.filterRunsTable();
        });
    }
})();"""

    runs_filter_js = """(function() {
    var tbody = document.querySelector('.runs-table tbody');
    var summary = document.querySelector('.runs-details summary');
    var defaultSummary = summary ? summary.textContent : '';
    if (!tbody) return;

    function toNumber(value) {
        var n = Number.parseFloat(value);
        return Number.isFinite(n) ? n : 0;
    }

    function stripZeros(text) {
        return text.replace(/\\.0+$/, '').replace(/(\\.\\d*[1-9])0+$/, '$1');
    }

    function compactTokenValue(value) {
        if (!value || value <= 0) return 'n/a';
        if (value >= 1e9) return stripZeros((value / 1e9).toFixed(value >= 10e9 ? 1 : 2)) + 'B';
        if (value >= 1e6) return stripZeros((value / 1e6).toFixed(1)) + 'M';
        if (value >= 1e3) return stripZeros((value / 1e3).toFixed(value >= 100e3 ? 0 : 1)) + 'K';
        return String(Math.round(value));
    }

    function formatDurationTotal(seconds) {
        var total = Math.round(seconds || 0);
        if (total <= 0) return 'n/a';
        var days = Math.floor(total / 86400);
        total -= days * 86400;
        var hours = Math.floor(total / 3600);
        total -= hours * 3600;
        var minutes = Math.floor(total / 60);
        var parts = [];
        if (days) parts.push(days + 'd');
        if (hours || days) parts.push(hours + 'h');
        parts.push(minutes + 'm');
        return parts.join(' ');
    }

    function formatCost(value) {
        if (!value || value <= 0) return 'n/a';
        return '$' + value.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2});
    }

    function resourceStatsText(nRuns, durationTotal, durationRuns, tokenInTotal, tokenOutTotal, tokenRuns, costTotal, costRuns) {
        var durationLabel = formatDurationTotal(durationTotal);
        if (durationRuns && durationRuns !== nRuns) {
            durationLabel += ' (timing data for ' + durationRuns + '/' + nRuns + ' runs)';
        }

        var tokenTotal = tokenInTotal + tokenOutTotal;
        var tokenLabel = tokenTotal > 0
            ? compactTokenValue(tokenTotal) + ' (' + compactTokenValue(tokenInTotal) + ' in, ' + compactTokenValue(tokenOutTotal) + ' out)'
            : 'n/a';
        if (tokenTotal > 0 && tokenRuns !== nRuns) {
            tokenLabel += ' (token data for ' + tokenRuns + '/' + nRuns + ' runs)';
        }

        var costLabel = formatCost(costTotal);
        if (costRuns && costRuns !== nRuns) {
            costLabel += ' (cost data for ' + costRuns + '/' + nRuns + ' runs)';
        }

        return 'Total runtime: ' + durationLabel
            + ' · Total tokens: ' + tokenLabel
            + ' · Total cost: ' + costLabel + '.';
    }

    window.filterRunsTable = function() {
        // Collect visible (agent, model) pairs from chart
        var visible = {};
        document.querySelectorAll('.model-group').forEach(function(g) {
            if (g.classList.contains('model-hidden') || g.classList.contains('model-hidden-user') || g.classList.contains('metric-hidden')) return;
            var model = g.getAttribute('data-model');
            g.querySelectorAll('.bar-wrapper').forEach(function(w) {
                if (w.classList.contains('agent-hidden')) return;
                if (w.style.display === 'none') return;
                visible[w.getAttribute('data-agent') + '|' + model] = true;
            });
        });

        var total = 0, shown = 0;
        var taskCounts = {};
        var nVisibleRuns = 0;
        var durationTotal = 0;
        var durationRuns = 0;
        var tokenInTotal = 0;
        var tokenOutTotal = 0;
        var tokenRuns = 0;
        var costTotal = 0;
        var costRuns = 0;
        Array.prototype.slice.call(tbody.rows).forEach(function(row) {
            total++;
            var key = row.getAttribute('data-agent') + '|' + row.getAttribute('data-model');
            var vis = !!visible[key];
            row.style.display = vis ? '' : 'none';
            if (vis) {
                shown++;
                nVisibleRuns++;
                try {
                    var passed = JSON.parse(row.getAttribute('data-passed') || '[]');
                    passed.forEach(function(t) { taskCounts[t] = (taskCounts[t] || 0) + 1; });
                } catch(e) {}
                var duration = toNumber(row.getAttribute('data-duration-sec'));
                if (duration > 0) {
                    durationTotal += duration;
                    durationRuns++;
                }
                var tokenIn = toNumber(row.getAttribute('data-token-input'));
                var tokenOut = toNumber(row.getAttribute('data-token-output'));
                if (tokenIn + tokenOut > 0) {
                    tokenInTotal += tokenIn;
                    tokenOutTotal += tokenOut;
                    tokenRuns++;
                }
                var cost = toNumber(row.getAttribute('data-cost-usd'));
                if (cost > 0) {
                    costTotal += cost;
                    costRuns++;
                }
            }
        });

        if (summary) {
            if (shown < total) {
                summary.textContent = 'Run Details (' + shown + ' of ' + total + ' runs)';
            } else {
                summary.textContent = defaultSummary;
            }
        }

        // Update task stats and resource totals
        var statsEl = document.getElementById('taskStats');
        if (statsEl) {
            var totalTasks = parseInt(statsEl.getAttribute('data-total-tasks')) || 89;
            var solvedOnce = Object.keys(taskCounts).length;
            var solvedAlways = 0;
            for (var t in taskCounts) { if (taskCounts[t] === nVisibleRuns) solvedAlways++; }
            var neverSolved = totalTasks - solvedOnce;
            var pct = function(x) { return Math.round(x / totalTasks * 100); };
            statsEl.textContent = 'Across these ' + nVisibleRuns + ' runs, '
                + solvedOnce + ' (' + pct(solvedOnce) + '%) of the ' + totalTasks + ' tasks were solved at least once, '
                + solvedAlways + ' (' + pct(solvedAlways) + '%) were solved every time, '
                + 'and ' + neverSolved + ' (' + pct(neverSolved) + '%) were never solved.';
        }
        var resourcesEl = document.getElementById('runResourceStats');
        if (resourcesEl) {
            resourcesEl.textContent = resourceStatsText(
                nVisibleRuns,
                durationTotal,
                durationRuns,
                tokenInTotal,
                tokenOutTotal,
                tokenRuns,
                costTotal,
                costRuns
            );
        }
    };
})();"""

    label_padding_js = """(function() {
    var chartScroll = document.querySelector('.chart-scroll');
    if (!chartScroll) return;
    var basePad = 24; // space between tallest label and scrollbar
    var highlightPad = 48; // extra room for the 4px model highlight border

    window.adjustLabelPadding = function() {
        var maxH = 0;
        var hasHighlight = false;
        document.querySelectorAll('.model-group').forEach(function(g) {
            if (g.classList.contains('model-hidden') || g.classList.contains('model-hidden-user') || g.classList.contains('metric-hidden')) return;
            if (g.classList.contains('model-highlighted')) hasHighlight = true;
            var lbl = g.querySelector('.model-label');
            if (lbl) {
                var h = lbl.offsetHeight;
                if (h > maxH) maxH = h;
            }
        });
        // margin-top on .model-label (6px) + label height + base padding
        chartScroll.style.paddingBottom = (6 + maxH + (hasHighlight ? highlightPad : basePad)) + 'px';
        if (window.WolfBenchRefreshModelHighlights) window.WolfBenchRefreshModelHighlights();
    };

    window.adjustLabelPadding();
    window.addEventListener('resize', function() { window.adjustLabelPadding(); });
    document.fonts.ready.then(function() { window.adjustLabelPadding(); });
})();"""

    token_depth_js = """(function() {
    var chartArea = document.querySelector('.chart-area');
    if (!chartArea) return;
    var urlState = window.WolfBenchUrlState ? window.WolfBenchUrlState.state : {};
    var tokenDepthModes = ['flat', 'tokens', 'cost', 'both'];
    var tokenDepthMode = normalizeTokenDepthMode(urlState && urlState.tokenDepth);
    window._tokenDepthMode = tokenDepthMode;
    window._tokenDepthEnabled = tokenDepthMode !== 'flat';

    function notifyUrlChange() {
        if (window.WolfBenchUrlState) window.WolfBenchUrlState.notifyChange();
    }

    function normalizeTokenDepthMode(mode) {
        if (mode === 'overlap' || mode === 'spaced' || mode === 'on' || mode === '3d') return 'tokens';
        if (mode === 'tokens' || mode === 'token') return 'tokens';
        if (mode === 'cost' || mode === 'costs' || mode === 'usd') return 'cost';
        if (mode === 'both' || mode === 'tokens+cost' || mode === 'tokens-cost' || mode === 'token+cost' || mode === 'token-cost' || mode === 'tokens_cost' || mode === 'combined') return 'both';
        return 'flat';
    }

    function nextTokenDepthMode(mode) {
        var index = tokenDepthModes.indexOf(normalizeTokenDepthMode(mode));
        return tokenDepthModes[(index + 1) % tokenDepthModes.length];
    }

    function stripZeros(text) {
        return text.replace(/\\.0+$/, '').replace(/(\\.\\d*[1-9])0+$/, '$1');
    }

    function compactTokenValue(value) {
        if (!value) return '0';
        if (value >= 1e9) return stripZeros((value / 1e9).toFixed(value >= 10e9 ? 1 : 2)) + 'B';
        if (value >= 1e6) return stripZeros((value / 1e6).toFixed(1)) + 'M';
        if (value >= 1e3) return stripZeros((value / 1e3).toFixed(value >= 100e3 ? 0 : 1)) + 'K';
        return String(Math.round(value));
    }

    function formatCost(value, fallback) {
        if (!value || value <= 0) return fallback || '-';
        return '$' + value.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2});
    }

    function depthScaleLabelForMode(mode) {
        if (mode === 'tokens') return '3D depth scale: 1 px = 10M tokens · 100 px = 1B tokens';
        if (mode === 'cost') return '3D depth scale: 1 px = $5 run cost · 100 px = $500';
        if (mode === 'both') return '3D depth scale: Tokens 1 px = 10M · Cost shadow 1 px = $5';
        return '';
    }

    function updateDepthScaleLine(mode) {
        var line = document.getElementById('depthScaleLine');
        if (!line) return;
        var label = depthScaleLabelForMode(mode);
        line.hidden = !label;
        line.textContent = label;
    }

    function toNumber(value) {
        var n = Number.parseFloat(value);
        return Number.isFinite(n) ? n : 0;
    }

    var tokensPerDepthPixel = 1e7;
    var costPerDepthPixel = 5;
    var missingDepth = 0;
    var items = [];

    document.querySelectorAll('.bar-wrapper').forEach(function(wrapper, index) {
        var bar = wrapper.querySelector('.bar');
        if (!bar) return;
        var input = toNumber(wrapper.getAttribute('data-token-input'));
        var output = toNumber(wrapper.getAttribute('data-token-output'));
        var total = toNumber(wrapper.getAttribute('data-token-total')) || input + output;
        var runs = toNumber(wrapper.getAttribute('data-token-runs')) || toNumber(wrapper.getAttribute('data-runs'));
        var cost = toNumber(wrapper.getAttribute('data-cost-total'));
        var costRuns = toNumber(wrapper.getAttribute('data-cost-runs'));
        var missing = total <= 0;
        var data = {input: input, output: output, total: total, runs: runs, cost: cost, costRuns: costRuns};
        wrapper.setAttribute('data-token-index', String(index));
        wrapper.classList.toggle('token-missing', missing);
        items.push({wrapper: wrapper, bar: bar, data: data, missing: missing});
    });
    if (!items.length) return;

    var totals = items.map(function(item) { return item.data.total; }).filter(function(value) { return value > 0; });
    var min = totals.length ? Math.min.apply(Math, totals) : 0;
    var max = totals.length ? Math.max.apply(Math, totals) : 0;
    var costs = items.map(function(item) { return item.data.cost; }).filter(function(value) { return value > 0; });
    var minCost = costs.length ? Math.min.apply(Math, costs) : 0;
    var maxCost = costs.length ? Math.max.apply(Math, costs) : 0;

    chartArea.classList.add('svg-iso', 'three-bars');
    var tokenDepthToggle = addLegend(min, max, minCost, maxCost);
    setTokenDepthMode(tokenDepthMode, true);

    items.forEach(function(item) {
        updateDepthVars(item);
        appendTokenTitle(item);
    });

    function depthForTokens(total) {
        if (!total || total <= 0) return 0;
        return total / tokensPerDepthPixel;
    }

    function depthForCost(cost) {
        if (!cost || cost <= 0) return 0;
        return cost / costPerDepthPixel;
    }

    function depthForMode(item, mode) {
        if (mode === 'cost') return depthForCost(item.data.cost);
        return item.missing ? missingDepth : depthForTokens(item.data.total);
    }

    function updateDepthVars(item) {
        var depth = depthForMode(item, tokenDepthMode);
        item.wrapper.setAttribute('data-token-depth', depth.toFixed(1));
        item.wrapper.style.setProperty('--iso-depth', depth.toFixed(1) + 'px');
        item.bar.style.setProperty('--iso-depth', depth.toFixed(1) + 'px');
    }

    function updateAllDepthVars() {
        items.forEach(updateDepthVars);
    }

    function appendTokenTitle(item) {
        var link = item.wrapper.querySelector('.bar-link');
        if (!link) return;
        var base = link.getAttribute('data-base-title') || link.getAttribute('title') || '';
        link.setAttribute('data-base-title', base);
        var agentName = item.wrapper.getAttribute('data-agent-name') || item.wrapper.getAttribute('data-agent') || '';
        var agentVersion = item.wrapper.getAttribute('data-agent-version') || '';
        var agentLine = agentName ? '\\nAgent: ' + agentName + (agentVersion ? ' ' + agentVersion : '') : '';
        var unknownValueLabel = 'n/a';
        var costLabel = formatCost(item.data.cost, unknownValueLabel);
        var costSuffix = item.data.costRuns && item.data.costRuns !== item.data.runs
            ? ' (' + item.data.costRuns + ' costed runs)'
            : '';
        if (item.missing) {
            link.setAttribute('title', base
                + agentLine
                + '\\nTokens: ' + unknownValueLabel
                + '\\nCost: ' + costLabel + costSuffix
                + '\\nRuns: ' + item.data.runs);
            return;
        }
        var inputShare = item.data.total ? Math.round(item.data.input / item.data.total * 1000) / 10 : 0;
        var outputShare = item.data.total ? Math.round(item.data.output / item.data.total * 1000) / 10 : 0;
        link.setAttribute('title', base + agentLine + '\\nTokens:'
            + '\\n  In: ' + compactTokenValue(item.data.input) + ' (' + inputShare + '%)'
            + '\\n  Out: ' + compactTokenValue(item.data.output) + ' (' + outputShare + '%)'
            + '\\n  Total: ' + compactTokenValue(item.data.total)
            + '\\nCost: ' + costLabel + costSuffix
            + '\\nRuns: ' + item.data.runs);
    }

    function addLegend(minValue, maxValue, minCostValue, maxCostValue) {
        var legend = document.querySelector('.legend');
        var existing = document.getElementById('svgIsoLegend');
        if (!legend || existing) return existing;
        var el = document.createElement('span');
        el.className = 'svg-iso-legend active';
        el.id = 'svgIsoLegend';
        el.setAttribute('role', 'button');
        el.setAttribute('tabindex', '0');
        el.setAttribute('aria-pressed', 'true');
        el.title = 'Bars are in 2D. Click for 3D: Tokens.';
        el.innerHTML = '<span class="svg-iso-swatch"><span class="svg-iso-split"></span></span><span class="svg-iso-label">Bars: 2D</span>';
        el.setAttribute('data-token-range', compactTokenValue(minValue) + '-' + compactTokenValue(maxValue));
        el.setAttribute('data-token-scale', 'linear;10M=1px;1B=100px;uncapped');
        el.setAttribute('data-cost-range', formatCost(minCostValue) + '-' + formatCost(maxCostValue));
        el.setAttribute('data-cost-scale', 'absolute-linear;$5=1px;$500=100px;uncapped');
        el.addEventListener('click', function(event) {
            event.stopPropagation();
            setTokenDepthMode(nextTokenDepthMode(tokenDepthMode), false);
        });
        el.addEventListener('keydown', function(event) {
            if (event.key !== 'Enter' && event.key !== ' ') return;
            event.preventDefault();
            setTokenDepthMode(nextTokenDepthMode(tokenDepthMode), false);
        });
	        var exportSep = document.getElementById('chartExportSep');
	        if (exportSep && exportSep.parentNode === legend) {
	            legend.insertBefore(el, exportSep);
	        } else {
	            legend.appendChild(el);
	        }
	        return el;
	    }

    function setTokenDepthMode(mode, initializing) {
        tokenDepthMode = normalizeTokenDepthMode(mode);
        var enabled = tokenDepthMode !== 'flat';
        window._tokenDepthMode = tokenDepthMode;
        window._tokenDepthEnabled = enabled;
        chartArea.classList.toggle('token-depth-flat', tokenDepthMode === 'flat');
        chartArea.classList.toggle('token-depth-3d', enabled);
        chartArea.classList.toggle('token-depth-tokens', tokenDepthMode === 'tokens');
        chartArea.classList.toggle('token-depth-cost', tokenDepthMode === 'cost');
        chartArea.classList.toggle('token-depth-both', tokenDepthMode === 'both');
        chartArea.classList.toggle('token-depth-off', !enabled);
        updateAllDepthVars();
        if (tokenDepthToggle) {
            var label = tokenDepthToggle.querySelector('.svg-iso-label');
            tokenDepthToggle.classList.toggle('active', enabled);
            tokenDepthToggle.classList.toggle('dimmed', !enabled);
            tokenDepthToggle.setAttribute('aria-pressed', enabled ? 'true' : 'false');
            tokenDepthToggle.setAttribute('data-token-depth', tokenDepthMode);
            tokenDepthToggle.setAttribute('aria-label', 'Bar depth mode: ' + tokenDepthMode);
            if (tokenDepthMode === 'flat') {
                if (label) label.textContent = 'Bars: 2D';
                tokenDepthToggle.title = 'Bars are in 2D. Click for 3D: Tokens.';
            } else if (tokenDepthMode === 'tokens') {
                if (label) label.textContent = 'Bars: 3D Tokens';
                tokenDepthToggle.title = '3D bars use uncapped absolute linear total token volume: 1px = 10M tokens. Front depth is input, rear depth is output. Click for 3D Cost.';
            } else if (tokenDepthMode === 'cost') {
                if (label) label.textContent = 'Bars: 3D Cost';
                tokenDepthToggle.title = '3D bars use uncapped absolute linear run cost: 1px = $5. No log scale, no per-chart normalization. Click for 3D Tokens + Cost.';
            } else {
                if (label) label.textContent = 'Bars: 3D Tokens + Cost';
                tokenDepthToggle.title = 'Main bar uses token depth; the neutral gray shadow uses run cost. Click for 2D bars.';
            }
        }
        updateDepthScaleLine(tokenDepthMode);
        if (initializing) return;
        if (window.updateChartWidth) window.updateChartWidth();
        if (window.adjustLabelPadding) window.adjustLabelPadding();
        if (window.WolfBenchThreeBars) window.WolfBenchThreeBars.render();
        document.dispatchEvent(new CustomEvent('wolfbench:token-depth-change', {detail: {mode: tokenDepthMode}}));
        notifyUrlChange();
    }
})();"""

    url_finish_js = """if (window.WolfBenchUrlState) window.WolfBenchUrlState.finishBoot();"""

    all_js = (url_state_js + "\n" + longpress_js + "\n" + agent_toggle_js + "\n" + metric_filter_js + "\n"
              + unit_toggle_js + "\n" + chart_screenshot_js + "\n" + model_toggle_js + "\n" + model_highlight_js + "\n"
              + bar_drag_js + "\n" + runs_filter_js + "\n"
              + label_padding_js + "\n" + table_sort_js + "\n"
              + token_depth_js + "\n" + url_finish_js)

    ch = CHART_HEIGHT  # alias
    ppx = PX_PER_PCT

    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>WolfBench</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Source+Sans+3:wght@400;500;600;700;800&family=Source+Serif+4:wght@600;700;800&display=swap');

* {{ margin: 0; padding: 0; box-sizing: border-box; }}

body {{
    font-family: 'Source Sans 3', -apple-system, sans-serif;
    background: #1A1C1F;
    color: #e6edf3;
    min-height: 100vh;
    padding: 48px 32px;
}}

.container {{
    margin: 0 auto;
}}

/* Header */
.header {{
    display: grid;
    grid-template-columns: minmax(72px, 1fr) auto minmax(180px, 1fr);
    align-items: center;
    justify-content: center;
    gap: 24px;
    margin-bottom: 8px;
}}

.header-logo {{
    flex-shrink: 0;
    object-fit: contain;
}}
.header-logo-wolfbench {{
    width: 58px;
    height: 58px;
    border-radius: 50%;
    justify-self: end;
}}
.header-logo-wandb {{
    width: auto;
    height: 58px;
    max-height: 58px;
    justify-self: start;
    margin-left: -11px;
}}

h1 {{
    font-family: 'Source Serif 4', Georgia, serif;
    font-size: 2.4rem;
    font-weight: 800;
    letter-spacing: 0;
    color: #FFCC33;
}}

@media (max-width: 720px) {{
    .header {{
        grid-template-columns: 48px minmax(0, auto) 132px;
        gap: 12px;
    }}
    .header-logo-wolfbench {{
        width: 44px;
        height: 44px;
    }}
    .header-logo-wandb {{
        width: auto;
        height: 44px;
        max-height: 44px;
        margin-left: -8px;
    }}
    h1 {{
        font-size: 1.8rem;
    }}
}}

.subtitle {{
    text-align: center;
    color: #9BA1A6;
    font-size: 1rem;
    margin-bottom: 28px;
    font-weight: 500;
}}

/* Preview note */
.preview-note {{
    max-width: 690px;
    margin: 0 auto 28px;
    padding: 14px 20px;
    background: rgba(46,51,56,0.4);
    border: 1px solid #2E3338;
    border-left: 3px solid #FFCC33;
    border-radius: 6px;
    color: #9BA1A6;
    font-size: 0.92rem;
    line-height: 1.6;
}}
.preview-note strong {{
    color: #e6edf3;
}}

/* Hook / intro */
.hook {{
    text-align: center;
    max-width: 690px;
    margin: 0 auto 36px;
}}
.hook-headline {{
    font-family: 'Source Serif 4', Georgia, serif;
    font-size: 1.35rem;
    font-weight: 800;
    color: #FFCC33;
    margin-bottom: 10px;
}}
.hook p {{
    color: #9BA1A6;
    font-size: 0.95rem;
    line-height: 1.65;
}}
.hook strong {{ color: #e6edf3; }}


/* Legend */
.legend {{
    position: relative;
    z-index: 10;
    display: flex;
    justify-content: center;
    align-items: center;
    gap: 14px;
    flex-wrap: wrap;
    margin-bottom: 8px;
    padding: 18px 28px;
    background: rgba(26,28,31,0.8);
    border: 1px solid #2E3338;
    border-radius: 12px;
    backdrop-filter: blur(8px);
}}

.legend-agent {{
    display: inline-flex;
    align-items: center;
    gap: 8px;
    padding: 7px 13px 6px 10px;
    border-radius: 6px;
    font-weight: 600;
    font-size: 0.95rem;
    line-height: 1;
    cursor: grab;
    user-select: none;
    transition: opacity 0.25s ease, transform 0.15s ease;
}}
.legend-agent:hover {{ transform: translateY(-1px); }}
.legend-agent:active {{ cursor: grabbing; }}
.legend-agent[draggable="false"] {{ cursor: pointer; }}
.legend-agent[draggable="false"]:active {{ cursor: pointer; }}
.legend-agent.dimmed {{ opacity: 0.3; }}
.legend-agent.unavailable {{ display: none; }}
.legend-agent.dragging {{ opacity: 0.5; transform: scale(0.95); }}
.legend-agent.drag-over {{ filter: brightness(1.4); }}
.legend-agent-terminus-2   {{ background: rgba(39,174,96,0.2);  color: #58d68d; border: 1px solid rgba(39,174,96,0.3); }}
.legend-agent-claude-code  {{ background: rgba(230,126,34,0.2); color: #f0b27a; border: 1px solid rgba(230,126,34,0.3); }}
.legend-agent-hermes {{ background: rgba(241,196,15,0.2); color: #f4d03f; border: 1px solid rgba(241,196,15,0.3); }}
.legend-agent-openclaw     {{ background: rgba(231,76,60,0.2);  color: #f1948a; border: 1px solid rgba(231,76,60,0.3); }}
.legend-agent-cline-cli    {{ background: rgba(142,68,173,0.2); color: #bb8fce; border: 1px solid rgba(142,68,173,0.3); }}
.legend-agent-cursor-cli   {{ background: rgba(52,152,219,0.2); color: #85c1e9; border: 1px solid rgba(52,152,219,0.3); }}
.legend-agent-codex        {{ background: rgba(99,102,241,0.2); color: #a5b4fc; border: 1px solid rgba(99,102,241,0.3); }}
.legend-agent-name {{
    white-space: nowrap;
}}
.agent-logo {{
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 16px;
    height: 16px;
    flex: 0 0 auto;
    color: currentColor;
}}
.agent-logo svg {{
    display: block;
    width: 100%;
    height: 100%;
}}
.agent-logo:not(.agent-logo-branded) svg {{
    fill: currentColor;
}}
.agent-logo img {{
    display: block;
    width: 100%;
    height: 100%;
    object-fit: contain;
    border-radius: 50%;
}}
.agent-logo:not(.agent-logo-branded) svg * {{
    fill: currentColor;
}}

.legend-toggle {{
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 32px;
    padding: 7px 0 6px;
    border-radius: 6px;
    font-weight: 700;
    font-size: 0.95rem;
    line-height: 1;
    cursor: pointer;
    user-select: none;
    background: rgba(46,51,56,0.5);
    border: 1px solid #2E3338;
    color: #FFCC33;
    transition: opacity 0.25s ease, transform 0.15s ease, border-color 0.2s ease;
}}
.legend-toggle:hover {{ transform: translateY(-1px); border-color: #FFCC33; background: rgba(255,204,51,0.1); }}
.legend-toggle.active {{ border-color: #FFCC33; background: rgba(255,204,51,0.1); }}
.legend-toggle[data-sort-mode="2"] {{ background: rgba(255,204,51,0.28); color: #FFE680; }}
#chartSaveToggle.copying {{
    opacity: 0.65;
    pointer-events: none;
}}
#chartSaveToggle.saved {{
    border-color: #58d68d;
    color: #58d68d;
    background: rgba(39,174,96,0.12);
}}
#chartSaveToggle.partial {{
    border-color: #f1c40f;
    color: #f4d03f;
    background: rgba(241,196,15,0.12);
}}
#chartSaveToggle.failed {{
    border-color: #e74c3c;
    color: #f1948a;
    background: rgba(231,76,60,0.12);
}}

.legend-sep {{
    width: 1px;
    background: #2E3338;
    margin: 0 6px;
}}

.legend-metric {{
    display: inline-flex;
    align-items: center;
    padding: 7px 12px 6px;
    border-radius: 6px;
    font-size: 0.9rem;
    font-weight: 500;
    background: rgba(46,51,56,0.5);
    border: 1px solid #2E3338;
    line-height: 1;
    cursor: pointer;
    user-select: none;
    transition: opacity 0.25s ease, transform 0.15s ease, border-color 0.2s ease;
}}
.legend-metric:hover {{ transform: translateY(-1px); }}
.legend-metric.active {{ border-color: #FFCC33; background: rgba(255,204,51,0.1); }}
.legend-metric.dimmed {{ opacity: 0.3; }}
.legend-metric small {{ color: #6B7280; }}

.depth-scale-line {{
    display: block;
    color: inherit;
    font-size: inherit;
    line-height: inherit;
    margin-top: 0;
}}
.depth-scale-line[hidden] {{ display: none; }}

/* Model bar — toggle visibility and drag to reorder */
.model-bar {{
    display: flex;
    justify-content: center;
    align-items: center;
    gap: 10px;
    flex-wrap: wrap;
    margin-bottom: 8px;
    padding: 14px 28px;
    background: rgba(26,28,31,0.8);
    border: 1px solid #2E3338;
    border-radius: 12px;
    backdrop-filter: blur(8px);
}}

/* Agent bar — directly above chart for clear color association */
.agent-bar {{
    display: flex;
    justify-content: center;
    align-items: center;
    gap: 14px;
    flex-wrap: wrap;
    margin-bottom: 24px;
    padding: 14px 28px;
    background: rgba(26,28,31,0.8);
    border: 1px solid #2E3338;
    border-radius: 12px;
    backdrop-filter: blur(8px);
}}
.model-btn {{
    display: inline-flex;
    align-items: center;
    padding: 7px 14px 6px;
    border-radius: 6px;
    font-weight: 600;
    font-size: 0.92rem;
    line-height: 1;
    cursor: grab;
    user-select: none;
    background: rgba(46,51,56,0.5);
    border: 1px solid #2E3338;
    color: #e6edf3;
    transition: opacity 0.25s ease, transform 0.15s ease, border-color 0.2s ease;
}}
.model-btn:hover {{
    transform: translateY(-1px);
    border-color: #FFCC33;
    background: rgba(255,204,51,0.08);
}}
.model-btn.dimmed {{ opacity: 0.3; }}
.model-btn.unavailable {{ display: none; }}
.model-btn:active {{ cursor: grabbing; }}
.model-btn.dragging {{ opacity: 0.5; transform: scale(0.95); }}
.model-btn.drag-over {{ border-color: #FFCC33; background: rgba(255,204,51,0.15); }}
#modelVisToggle.dimmed {{ opacity: 0.5; filter: grayscale(1); }}

/* Chart wrapper — flex layout with sticky y-axis */
.chart-wrapper {{
    display: flex;
    align-items: flex-start;
    margin-bottom: 20px;
}}
.y-axis {{
    width: 60px;
    flex-shrink: 0;
    position: relative;
    height: {ch}px;
    margin-top: 54px;
}}
.chart-scroll {{
    flex: 1;
    overflow-x: auto;
    overflow-y: hidden;
    min-width: 0;
    padding-top: 54px;
    padding-bottom: 0; /* set dynamically by JS */
    scrollbar-color: rgba(255,255,255,0.3) rgba(255,255,255,0.06);
}}
.chart-scroll::-webkit-scrollbar {{
    height: 28px;
}}
.chart-scroll::-webkit-scrollbar-track {{
    background: rgba(255,255,255,0.06);
    border-radius: 4px;
    border: 8px solid transparent;
    background-clip: content-box;
}}
.chart-scroll::-webkit-scrollbar-thumb {{
    background: rgba(255,255,255,0.3);
    border-radius: 4px;
    border: 8px solid transparent;
    background-clip: content-box;
}}
.chart-scroll::-webkit-scrollbar-thumb:hover {{
    background: rgba(255,255,255,0.45);
}}
.chart-area {{
    position: relative;
    height: {ch}px;
    min-width: {chart_min_w}px;
}}

/* Y-axis ticks — positioned absolutely relative to chart-area */
.y-tick {{
    position: absolute;
    right: 4px;
    font-size: 0.85rem;
    color: #9BA1A6;
    font-weight: 500;
    transform: translateY(50%);
    text-align: right;
    width: 48px;
}}

/* Grid lines */
.grid-line {{
    position: absolute;
    left: 0;
    right: 0;
    height: 1px;
    background: #2E3338;
    pointer-events: none;
}}

/* Models container — fills chart area, bars anchored to bottom */
.models-row {{
    position: absolute;
    bottom: 0;
    left: 0;
    right: 0;
    height: {ch}px;
    display: flex;
    justify-content: flex-start;
    gap: 64px;
    padding: 0 48px;
}}
.models-row.agent-filtered {{
    gap: 64px;
}}

.model-group {{
    display: flex;
    flex-direction: column;
    align-items: center;
    position: relative;
    --model-highlight-xpad: 28px;
    --model-highlight-left-pad: 28px;
    --model-highlight-right-pad: 28px;
    --model-label-height: 24px;
}}
.model-group.model-hidden, .model-group.metric-hidden {{
    display: none;
}}
.model-group.model-hidden-user {{
    display: none;
}}

.bars-row {{
    display: flex;
    gap: 8px;
    align-items: flex-end;
    justify-content: center;
    margin-top: auto;
}}

.model-label {{
    position: absolute;
    top: 100%;
    margin-top: 6px;
    left: 50%;
    transform: translateX(-50%);
    font-size: 1.1rem;
    font-weight: 700;
    color: #e6edf3;
    text-align: center;
    letter-spacing: -0.01em;
    width: max-content;
    max-width: calc(100% + 40px);
    overflow-wrap: break-word;
    line-height: 1.2;
    cursor: pointer;
    user-select: none;
    z-index: 8;
    padding: 2px 6px;
    border-radius: 6px;
    transition: color 0.2s ease;
}}
.model-label:hover {{
    color: #ffffff;
    text-shadow: 0 0 12px rgba(255,204,51,0.35);
}}
.model-label:focus-visible {{
    outline: 2px solid #FFCC33;
    outline-offset: 3px;
}}
.model-highlight-box {{
    display: none;
    position: absolute;
    box-sizing: border-box;
    left: calc(-1 * var(--model-highlight-left-pad, var(--model-highlight-xpad, 28px)));
    right: calc(-1 * var(--model-highlight-right-pad, var(--model-highlight-xpad, 28px)));
    top: -12px;
    bottom: calc(-1 * (var(--model-label-height, 24px) + 28px));
    background: transparent;
    border: 4px solid #e74c3c;
    border-radius: 10px;
    box-shadow: none;
    pointer-events: none;
    z-index: 7;
}}
.model-group.model-highlighted .model-highlight-box {{
    display: block;
}}
.model-group.model-highlighted .model-label {{
    color: #FFCC33;
    text-shadow: none;
}}
.model-group.model-highlighted .bars-row {{
    position: relative;
    z-index: 6;
}}

/* Bar */
.bar-wrapper {{
    display: flex;
    flex-direction: column;
    align-items: center;
    position: relative;
    transition: opacity 0.3s ease;
    cursor: grab;
}}
.bar-wrapper:active {{ cursor: grabbing; }}
.bar-wrapper.bar-dragging {{ opacity: 0.4; }}
.bar-wrapper.bar-drag-over {{ outline: 2px dashed rgba(255,204,51,0.6); outline-offset: 2px; border-radius: 6px; }}
.bar-wrapper.agent-hidden {{
    display: none;
}}

.bar-top-label {{
    position: absolute;
    bottom: calc(100% + 14px);
    left: 50%;
    transform: translateX(-50%);
    font-size: 1.05rem;
    font-weight: 700;
    color: #e6edf3;
    text-align: center;
    line-height: 1.2;
    white-space: nowrap;
    transition: transform 0.3s ease;
}}
.version-label {{
    font-size: 0.75rem;
    font-weight: 500;
    color: #9BA1A6;
}}
.thinking-label {{
    font-size: 0.75rem;
    font-weight: 600;
    color: #f0c040;
}}
.bar-bottom-label {{
    position: absolute;
    bottom: 7px;
    left: 50%;
    transform: translateX(-50%);
    text-align: center;
    white-space: nowrap;
    z-index: 8;
    pointer-events: none;
}}
.agent-badge {{
    display: inline-flex;
    align-items: center;
    justify-content: center;
    box-sizing: border-box;
    width: 40px;
    min-width: 40px;
    height: 40px;
    padding: 3px;
    color: currentColor;
    background-color: rgba(5,8,10,0.72);
    background-clip: padding-box;
    border: 1px solid rgba(255,255,255,0.16);
    border-radius: 50%;
    box-shadow: none;
    text-shadow: none;
    line-height: 0;
    overflow: hidden;
}}
.agent-badge .agent-logo {{
    width: 32px;
    height: 32px;
    padding: 0;
    border: 0;
    background: transparent;
    line-height: 0;
}}
.legend-agent-hermes .agent-badge,
.legend-agent-codex .agent-badge,
.bar-wrapper[data-agent="hermes"] .agent-badge,
.bar-wrapper[data-agent="codex"] .agent-badge {{
    color: #050810;
    background-color: #ffffff;
    border: 1px solid rgba(5,8,16,0.22);
}}
.legend-agent-claude-code .agent-badge,
.bar-wrapper[data-agent="claude-code"] .agent-badge {{
    color: #d97757;
    background-color: rgba(5,8,10,0.72);
    border: 1px solid rgba(240,178,122,0.32);
}}
.legend-agent-cline-cli .agent-badge,
.legend-agent-cursor-cli .agent-badge,
.bar-wrapper[data-agent="cline-cli"] .agent-badge,
.bar-wrapper[data-agent="cursor-cli"] .agent-badge {{
    color: #ffffff;
    background-color: #050810;
    border: 1px solid rgba(255,255,255,0.22);
}}
.legend-agent-terminus-2 .agent-badge,
.bar-wrapper[data-agent="terminus-2"] .agent-badge {{
    background-color: #050810;
    border-color: rgba(39,174,96,0.3);
}}
.legend-agent-claude-code .agent-badge,
.bar-wrapper[data-agent="claude-code"] .agent-badge {{ border-color: rgba(230,126,34,0.3); }}
.legend-agent-hermes .agent-badge,
.bar-wrapper[data-agent="hermes"] .agent-badge {{ border-color: rgba(241,196,15,0.3); }}
.legend-agent-openclaw .agent-badge,
.bar-wrapper[data-agent="openclaw"] .agent-badge {{ border-color: rgba(231,76,60,0.3); }}
.legend-agent-cline-cli .agent-badge,
.bar-wrapper[data-agent="cline-cli"] .agent-badge {{ border-color: rgba(142,68,173,0.3); }}
.legend-agent-cursor-cli .agent-badge,
.bar-wrapper[data-agent="cursor-cli"] .agent-badge {{ border-color: rgba(52,152,219,0.3); }}
.legend-agent-codex .agent-badge,
.bar-wrapper[data-agent="codex"] .agent-badge {{ border-color: rgba(99,102,241,0.3); }}
.bar-link {{
    text-decoration: none;
    display: block;
    cursor: pointer;
}}
.bar-link:hover .bar {{
    filter: brightness(1.15);
    transition: filter 0.2s;
}}

.bar {{
    position: relative;
    box-shadow: 0 4px 24px rgba(0,0,0,0.4), 0 0 1px rgba(255,255,255,0.1);
}}


.bar-inner {{
    position: relative;
    width: 100%;
}}

.bar-segments {{
    display: flex;
    flex-direction: column;
    justify-content: flex-end;
    height: 100%;
    width: 100%;
    border-radius: 8px 8px 4px 4px;
    overflow: hidden;
}}

.bar-labels {{
    position: absolute;
    bottom: 0;
    left: 0;
    right: 0;
    height: 100%;
    pointer-events: none;
}}

/* Segment */
.segment {{
    position: relative;
    overflow: hidden;
    display: flex;
    align-items: center;
    justify-content: center;
    border-bottom: 1px solid rgba(0,0,0,0.2);
    transition: background 0.3s ease, box-shadow 0.3s ease;
}}

.segment:first-child {{
    border-radius: 8px 8px 0 0;
}}
.segment:last-child {{
    border-radius: 0 0 4px 4px;
    border-bottom: none;
}}

/* Metallic shine overlay */
.segment-shine {{
    position: absolute;
    top: 0; left: 12%; bottom: 0;
    width: 28%;
    background: linear-gradient(90deg, transparent, rgba(255,255,255,0.13), transparent);
    pointer-events: none;
}}

.seg-label {{
    position: absolute;
    left: 50%;
    transform: translateX(-50%) translateY(50%);
    display: inline-flex;
    align-items: baseline;
    gap: 1px;
    font-size: 0.85rem;
    font-weight: 800;
    color: white;
    text-shadow:
        -1px -1px 0 rgba(0,0,0,0.8),
         1px -1px 0 rgba(0,0,0,0.8),
        -1px  1px 0 rgba(0,0,0,0.8),
         1px  1px 0 rgba(0,0,0,0.8),
         0 0 6px rgba(0,0,0,0.6);
    z-index: 2;
    white-space: nowrap;
    letter-spacing: 0.02em;
}}
.seg-sym {{
    display: inline-block;
    width: 1em;
    text-align: center;
    flex-shrink: 0;
}}
.seg-pct {{
    text-align: right;
}}
.seg-label-sort {{
    color: #FFCC33 !important;
}}

/* Best-of / worst-of: hidden by default, visible on hover or metric filter */
.seg-label[data-metric="best"],
.seg-label[data-metric="worst"] {{
    opacity: 0;
    transition: opacity 0.2s ease;
}}
.bar-wrapper:hover .seg-label[data-metric="best"],
.bar-wrapper:hover .seg-label[data-metric="worst"] {{
    opacity: 1;
}}
.chart-area.metric-filter-best .seg-label[data-metric="best"],
.chart-area.metric-filter-worst .seg-label[data-metric="worst"] {{
    opacity: 1;
}}

	/* Footer */
.footer {{
    text-align: center;
    margin-top: 16px;
    color: #9BA1A6;
    font-size: 0.8rem;
    line-height: 1.45;
}}

/* About section */
.about {{
    max-width: 760px;
    margin: 48px auto 0;
}}
.about h2 {{
    font-family: 'Source Serif 4', Georgia, serif;
    font-size: 1.6rem;
    font-weight: 800;
    color: #FFCC33;
    margin-bottom: 12px;
}}
.about h3 {{
    font-family: 'Source Serif 4', Georgia, serif;
    font-size: 1.2rem;
    font-weight: 700;
    color: #e6edf3;
    margin-top: 28px;
    margin-bottom: 8px;
}}
.about p {{
    color: #c9d1d9;
    font-size: 0.95rem;
    line-height: 1.7;
    margin-bottom: 12px;
}}
.about strong {{ color: #e6edf3; }}
.about em {{ color: #10BFCC; font-style: italic; }}
.about ul {{
    color: #c9d1d9;
    font-size: 0.95rem;
    line-height: 1.7;
    margin: 8px 0 16px 20px;
}}
.about li {{ margin-bottom: 4px; }}
.about a {{
    color: #FFCC33;
    text-decoration: none;
    border-bottom: 1px solid rgba(255,204,51,0.3);
}}
.about a:hover {{ border-bottom-color: #FFCC33; }}
.about .tagline a:has(> .avatar) {{
    border-bottom: none;
    line-height: 0;
}}
.about .tagline {{
    color: #9BA1A6;
    font-style: italic;
    font-size: 0.95rem;
    margin-bottom: 24px;
    display: flex;
    align-items: center;
    gap: 10px;
}}
.about .tagline span {{
    flex: 1;
}}
.about .tagline .avatar {{
    width: 32px;
    height: 32px;
    border-radius: 50%;
    flex-shrink: 0;
}}
.about .metric-block {{
    background: rgba(46,51,56,0.4);
    border: 1px solid #2E3338;
    border-radius: 8px;
    padding: 14px 18px;
    margin-bottom: 10px;
}}
.about .metric-block h3 {{
    margin-top: 0;
    margin-bottom: 4px;
    font-size: 1.05rem;
}}
.about .metric-block p {{ margin-bottom: 6px; }}
.about .metric-block p:last-child {{ margin-bottom: 0; }}
.about .spread-list {{ margin-top: 12px; }}
.about .spread-list li {{
    padding: 4px 0;
}}
.about .build-info {{
    color: #6B7280;
    font-size: 0.85rem;
    margin-top: 32px;
    padding-top: 20px;
    border-top: 1px solid #2E3338;
    text-align: center;
}}

/* Metric-filter overrides (generated from AGENT_CONFIG gradients) */
.chart-area[class*="metric-filter"] .bar {{
    box-shadow: none !important;
}}
.chart-area[class*="metric-filter"] .bar-segments {{
    height: auto;
    position: absolute;
    bottom: 0;
    left: 0;
    right: 0;
}}
.chart-area[class*="metric-filter"] .segment {{
    background: transparent !important;
    box-shadow: none !important;
    border-bottom: none !important;
}}
.chart-area[class*="metric-filter"] .segment-shine {{
    display: none !important;
}}
	{metric_filter_css}
{runs_table_css}
{token_depth_css}
</style>
</head>
<body>
	<div class="container">
	    <div class="header">
	        <img class="header-logo header-logo-wolfbench" src="data:image/png;base64,{wolfbench_logo_b64}" alt="WolfBench" width="58" height="58">
	        <h1>WolfBench ({chart_date or date.today().isoformat()})</h1>
	        <img class="header-logo header-logo-wandb" src="data:image/png;base64,{wandb_cw_logo_b64}" alt="Weights &amp; Biases by CoreWeave" height="58">
	    </div>
    <p class="subtitle">Wolfram Ravenwolf&rsquo;s Five-Metric Framework &middot; based on Terminal-Bench 2.0{' &middot; min ' + str(min_runs) + ' runs' if min_runs > 1 else ''}</p>

    <div class="hook">
        <div class="hook-headline">One score is not enough.<br>Because performance is a distribution, not a point.</div>
        <p>Most benchmarks report a single average. <strong>WolfBench</strong> shows five metrics that tell the full story&nbsp;&ndash; from the <strong>rock-solid base</strong> of tasks solved every time, through the <strong>average</strong>, up to the <strong>ceiling</strong> of everything ever solved&nbsp;&ndash; plus the <strong>best</strong> and <strong>worst</strong> single runs that frame the spread. Together, they reveal what no single number can: how consistent an AI agent truly is.<br><a href="#about" style="color:#FFCC33; text-decoration:none; border-bottom:1px solid rgba(255,204,51,0.3);">Learn&nbsp;more&nbsp;&darr;</a></p>
    </div>

	    <div class="legend">
	        <span class="legend-toggle" id="unitToggle" data-mode="pct">%</span>
	        <div class="legend-sep"></div>
		        {"".join(legend_metrics)}
		        <div class="legend-sep" id="chartExportSep"></div>
		        <span class="legend-toggle" id="chartSaveToggle" role="button" tabindex="0" title="Save and copy full chart as PNG" aria-label="Save and copy full chart as PNG">&#x1F4F8;</span>
		    </div>

    <div class="model-bar">
        <span class="legend-toggle" id="modelVisToggle" title="Show/hide all models">&#x1F441;</span>
        <div class="legend-sep"></div>
        {"".join(model_bar_buttons)}
    </div>

    <div class="agent-bar">
        <span class="legend-toggle" id="barSortToggle" data-sort-mode="0" title="Sort: by agent &rarr; by score &rarr; by best score (cross-agent)">&#x21C5;</span>
        <div class="legend-sep"></div>
        {"".join(legend_agents)}
    </div>

    <div class="chart-wrapper">
        <div class="y-axis">
            {"".join(f'<span class="y-tick" style="bottom: {v * ppx}px;" data-pct="{v}%" data-abs="{round(v / 100 * TOTAL_TASKS)}">{v}%</span>' for v in range(0, 101, 10))}
        </div>
        <div class="chart-scroll">
            <div class="chart-area">
                {"".join(f'<div class="grid-line" style="bottom: {v * ppx}px;"></div>' for v in range(0, 101, 10))}

                <div class="models-row">
                    {"".join(model_groups_html)}
                </div>
            </div>
        </div>
    </div>

    <p class="footer">Terminal-Bench 2.0 &middot; {DEFAULT_RUNS} runs @ {DEFAULT_TIMEOUT_H}h timeout &middot; 4 CPUs, 8 GB RAM, 10 GB Storage per task<br><span id="agentVersionLine">{agent_version_line}</span><span id="depthScaleLine" class="depth-scale-line" hidden></span></p>

    {runs_table_html}

    <div class="about" id="about">
        <h2>About WolfBench</h2>
        <p class="tagline"><a href="https://x.com/WolframRvnwlf"><img class="avatar" src="data:image/jpeg;base64,/9j/4AAQSkZJRgABAQAASABIAAD/4QBARXhpZgAATU0AKgAAAAgAAYdpAAQAAAABAAAAGgAAAAAAAqACAAQAAAABAAAAUKADAAQAAAABAAAAUAAAAAD/7QA4UGhvdG9zaG9wIDMuMAA4QklNBAQAAAAAAAA4QklNBCUAAAAAABDUHYzZjwCyBOmACZjs+EJ+/+ICZElDQ19QUk9GSUxFAAEBAAACVGxjbXMEMAAAbW50clJHQiBYWVogB+kAAQAbABIAJQAvYWNzcE1TRlQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAPbWAAEAAAAA0y1sY21zAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAALZGVzYwAAAQgAAAA+Y3BydAAAAUgAAABMd3RwdAAAAZQAAAAUY2hhZAAAAagAAAAsclhZWgAAAdQAAAAUYlhZWgAAAegAAAAUZ1hZWgAAAfwAAAAUclRSQwAAAhAAAAAgZ1RSQwAAAhAAAAAgYlRSQwAAAhAAAAAgY2hybQAAAjAAAAAkbWx1YwAAAAAAAAABAAAADGVuVVMAAAAiAAAAHABzAFIARwBCACAASQBFAEMANgAxADkANgA2AC0AMgAuADEAAG1sdWMAAAAAAAAAAQAAAAxlblVTAAAAMAAAABwATgBvACAAYwBvAHAAeQByAGkAZwBoAHQALAAgAHUAcwBlACAAZgByAGUAZQBsAHlYWVogAAAAAAAA9tYAAQAAAADTLXNmMzIAAAAAAAEMQgAABd7///MlAAAHkwAA/ZD///uh///9ogAAA9wAAMBuWFlaIAAAAAAAAG+gAAA49QAAA5BYWVogAAAAAAAAJJ8AAA+EAAC2w1hZWiAAAAAAAABilwAAt4cAABjZcGFyYQAAAAAAAwAAAAJmZgAA8qcAAA1ZAAAT0AAACltjaHJtAAAAAAADAAAAAKPXAABUewAATM0AAJmaAAAmZgAAD1z/wAARCABQAFADASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9sAQwACAgICAgIEAgIEBgQEBAYIBgYGBggKCAgICAgKDAoKCgoKCgwMDAwMDAwMDg4ODg4OEBAQEBASEhISEhISEhIS/9sAQwEDAwMFBAUIBAQIEw0LDRMTExMTExMTExMTExMTExMTExMTExMTExMTExMTExMTExMTExMTExMTExMTExMTExMT/90ABAAF/9oADAMBAAIRAxEAPwD9/KKK+If2wv2rk+BPhqTQvBka33ie8QiCP7ywA9JHA5+g7n9ajBydoicktWfWfifxr4c8I2jXWt3Cx4GQo5Y/QV4xJ8c59XnMOg2wjTs8nU/hXwx8P9V8TeKvCcN54yuJLrVJrZHneXhvNZQW+Xtz27V734Oto40hnl/iUV5dfEyu4x0Pdw2CpqKnNXPb4PGnim7mG+fAPZRW/wD8JTr8YBWXJ9CK56witVIdfStn/R5Pm7CslOVtzaoobKP4GjD8UJrF9mrwhl/vJwfyr0rSPEmj62itYTBmYZ2nhvyr5l8SRK8MkkfH8I/E4r57/aGk8YWPw/vL74eTzW+tWaLLaNAQJDJGwYKAcKd2MYPBzW2HxEnNU3rc48ThYcjqR0sfp3RXyX+zF8d9f+I/h6Dw/wDEu2Fj4jhiVn4KJcJj/WKp5VuzKeh9Rgn60r1KlOUHyzVjx4zUleLP/9D9qPjV8T9M+D3w01Tx/qnK2MJZEyAXkPCqM9ya/ALQtZ8R/FfxNc/E/wAUytvnYSqxGdkjMCuc9cccDt9a+sf+Cr/xZksbTR/hVa5Im23cuDwCW2qX9gAcc9a+VvhD420/V9E0/wAB/ZljggzM8g4LsCp5Of8AZA9q76cXCjOUHaVroWG5amKpQqq8W7M+sfAetNb26yu247mjYj+8Dg19NeGrvTyiCS4jVj/DuGRXxJ8Krb+29G1Gxn3oWurlsA7WXc5O32wTisjWPhP4o1m9hRLuOwsopWMkKg7jGcYIkO5i/UnoD7V8q3GU7SPr3SlGNoq9j9T7BojATBMGxWpE4MRaaVQcdOlfD/wn1rUtD8TR+F0Zhp77im4ksFB43HAySOtZfxkOu+KNRn0Wwnkt0QyCKRWYfvNuU3YZTsLcHHOKzU1e1ip4bRs+ytWuYIkJDq+3nAIzXivizUJL2eCOJQ5llUKhOA2Pmxnt06186fD/AMC/ES0+z23iqRJfmLCS3mlWVOeCSWKv7ggZr1bxpcW+n+OfC2n3bEQrfsJMd8wSBRgdeSKanyVLw3RnHDe0SpzWjPE/in8ZYvg54st9ak+SeBg0bKD8kQJ3MCcEr2x1Nfrb8FfiroHxn+G+m/EHw7KskN7EC20g7XHDDj0NfjT+0d4Nh+OHgmbTfCWP7a8PTSW7JKPLe4QEhipJ5BYHBxjGOa9//wCCbWoP8MrAfATXJwb/AMiS+MQYkKxfkKT2xg8d819rjKdWpSjUqrZLU+HhKlTrTp0Xpd29Oh//0bn/AAVA8NxXfxLsddv5PKtrm38gMRnMiEEL9MH6V8sfs12umf8ACZtput3iQRRxN5IAxktxknHCliO9fff/AAUh8Hat4shlFjA8kmkxi7Xj5HSRtjKD3dducehr8c28Rr4X1NNZtb3y3MOAE4kLEDhh2AI55r21KMOWUlo1+h58XK/uPVP9T9Tvg7rUEl1qQiILxXUqkDnq3H6V9laXokepWAub3bhRnJ6fjX4z/s8/GtP+Esukv1EcdwFJGepUYJ+p61+meo/FpQLXw74fVWZ4/NlZycbewAGc18Xi4KnNpfI/QsuxanSTlubeiTWt58QYjphaZFcqX24UgcEL7V6HLFp9v4tmtdRYRLKSRvXKEdgT2PpXzZ4L8RfEnT/F7a5Hp6X1mhPlpbOkgYNnJGDnj0ru9V8bfEfUvFUmpT6Itvp/lgus7qmD6c9T7VzSVonbKXvX6H0rLosekW3n2SqQ3Prx7V81/EXWUi8d6IyIZJzLI4VevEDgmuv8GfFS21zSNQ0u7Q28un87Sdw2EHGD3xivz3+Mv7SsPgr4yaZObQala2oYXMIfZuWReivg7WAIOcexrrwUIVasVLbqeXmOJlSpOVPfoeS/Ev4h+PPBtwg0mQ2+tW8xnnm4cvJKS5jJHVMEDB4r7C/Y/wDGvjPxH8ZND8X+KfJhnnH2WRYhtOWyxGMn5cEV8SfEX4ifDH4neIo9U0m6uNO3FTJDfBRgA52iRSwb6nHB6Cv0i/Zbl8Na74x8K6f4ct4R9mzJK8RDlyBu3Mw74I4PNfdzcZwqS59LaI/PopqcLx1uf//S9R/4K3SfEzw1pOh6/wCGb+a20O7ZobuOHC/vv4SzgbsEZGM4r+f8vLLM0krFj1JPvX9nX7RfwY0f49/CXVfh1qoAa6jLW8hH+rmXlGH41/H58Qfh/wCI/hl4y1LwP4rga3vtPk8t1YYzgnDD1BHIraMrqzJtbYoeDrm7i8TW6WJxLMdif73Yfj0r7Z8A/G/U9K8VaNNqY5sGeKVXBDDJxtI9q+CbG4ms7qG+tj+8t3WRfqpzX6X6j8Ibb43+EbD4kfDd4otWeIGRCdqykcEN6OpGM/nXFi4xvea0Z6ODnKzUHqj6f1rx58PvCqx+KltGlS+w37ptpye+ByDXqfgLxB8PtdtB4xeFoUgTzAs7bsY5LYPOa/L+7u/iT4HeLTvGOj3UbQEKCULoQCeQy5B6+td54T0742fEsyaF4M02WG2dQjXN0GiiRSeSCRk/RQa8+VJ2s5aHuPM6jhya+h6ZqHxigL6tYeEbUy3+pXsqQBTuZ2JBjPH8IXOe1fFP7Qejr4d8X2uhSSme4ih824kPUyyct+GeB7Cv048C/Bjwj8APDNz4g8SXaXurCItNdOMCNByVjB+6PU9T3r8d/H/jGfx7421PxbLnZdzMYge0YOFH5V04KmnPmjsjycbVfJyyerOPnkPmqQetftR/wSK+Gd9d6/rvxUvFZbW2jFnB12tI3LH04FfkD4I8DeIviT4x0zwV4Wga4vb+XykVRnGcZJ9AOpr+u79nP4MaT8BvhLpfw90wAyW8Ye4kH/LSZuXb8+BXqTfQ8lI//9P9/K/PP9t39iDRP2j9HbxZ4VCWfiq0jxHJ0W4Uf8s39/Q1+hlFNOwH8SPjv4eeMPhf4nn8K+NrCWwvLdirJIpGfcHoQfUV9Ffsu/GbT/h5rJ8OeJLtrOxuXDxXBOY4nPUOOyse46HrX9OXxo/Zz+Evx70g6X8RdKjuXAxHcKNs0Z9Vcc1+QXxX/wCCQviW1uZbz4Ra5Fc25yUt70FZB7bxwfyqpKNRcsiqc3TlzRPsTQrdPEujRXW6K4VlDB0IKsD0IPcGoNVvovDVm671izwMHn8K/ObwT+zh+3/8A7z7P4W0x72wB+a280SwMP8AZGcr9VxXpPj34U/ty/GLT4tE0bwy+gRTJi6lmmUOSeqow5VffqfauT6nG568MfT5LyWp8u/tb/H1Nbll+HXhKfzVGRfTDnn/AJ5qemf7x7dPWvkfwH8PfFnxD1228I+CrGW/vbghVSJSevcnoB7mv1u+E/8AwSH8TXUyX3xc12O2jJBeCzG+Q/V24r9fPgz+zp8J/gPpI034faXHBIQBJcuA00nuznn8BXXDlpq0TyatR1ZczPmX9iT9iPR/2dtIXxb4tVLvxTdJ879Vt1P8Ce/qa/QyiipbvqyD/9k=" alt="Wolfram Ravenwolf"></a><span>by <a href="https://x.com/WolframRvnwlf">Wolfram Ravenwolf</a>&nbsp;&ndash; who evaluates models for breakfast, builds agents at night, and preaches AI usefulness all day long.</span></p>

        <blockquote class="preview-note">
            <strong>Welcome to WolfBench&nbsp;&ndash; we&rsquo;re just getting started.</strong> What you see here is an early preview with only a handful of models and agents tested so far. We&rsquo;re continuously expanding the lineup, running fresh evals, and sharing interesting findings and insights along the way. Watch this space.
        </blockquote>

        <p>AI agents are becoming essential tools. Every week, a new model comes out and claims to be &ldquo;the best at coding&rdquo; or &ldquo;SOTA on agentic tasks.&rdquo; But what does that actually mean for you&nbsp;&ndash; the person who&rsquo;s going to throw real work at these things?</p>
        <p><strong>A single score tells you almost nothing.</strong></p>
        <p>Most benchmarks give you one number: &ldquo;Model X scored 42% on Benchmark Y.&rdquo; Great. But can you <em>rely</em> on it? Was that a lucky run? Would it score the same tomorrow? What&rsquo;s the floor&nbsp;&ndash; the tasks it <em>always</em> nails? What&rsquo;s the ceiling&nbsp;&ndash; what it <em>could</em> do if the stars align?</p>
        <p><strong>WolfBench</strong> exists because we got tired of meaningless leaderboards. We wanted to know which model, which agent, and which settings actually deliver the best results on real agentic tasks&nbsp;&ndash; not just on paper, but in practice, consistently, across multiple runs.</p>

        <h3>What is it?</h3>
        <p><strong>WolfBench</strong> is an evaluation framework built on top of Terminal-Bench 2.0, a popular agentic benchmark consisting of 89 diverse real-world tasks. These aren&rsquo;t just coding puzzles. They span the kind of work you&rsquo;d actually ask an AI agent to do:</p>
        <ul>
            <li><strong>System administration:</strong> headless terminal interaction, Git server configuration, Nginx request logging</li>
            <li><strong>DevOps &amp; infrastructure:</strong> package distribution search, database WAL recovery, PyPI server setup</li>
            <li><strong>Security:</strong> code vulnerability fixes, 7z hash cracking, ELF binary extraction, Git leak recovery</li>
            <li><strong>Data &amp; ML ops:</strong> financial document processing, HuggingFace model inference, scientific stack modernization</li>
            <li><strong>Problem solving:</strong> constraint scheduling, adaptive rejection sampling, concurrent task cancellation</li>
        </ul>
        <p>The key word is <em>agentic</em>: these tasks require the model to plan, execute shell commands, inspect results, debug failures, and iterate&nbsp;&ndash; just like a human developer or sysadmin would. No multiple-choice shortcuts. No toy puzzles. Real work in real sandboxed environments.</p>

        <h3>Why WolfBench is different</h3>
        <ul>
            <li><strong>Five-metric framework:</strong> Instead of a single average score, we report five complementary metrics that together paint a far more complete picture of what an AI agent can actually do&nbsp;&ndash; from the worst-case floor to the theoretical ceiling.</li>
            <li><strong>Uniform conditions:</strong> Instead of Terminal-Bench 2.0&rsquo;s default task-specific timeouts and varying sandbox resources, every task in a run gets the same timeout and identical sandbox resources. This ensures scores reflect model and agent capability&nbsp;&ndash; not whether an inference endpoint was temporarily overloaded or a sandbox ran out of memory.</li>
            <li><strong>Multi-agent comparison:</strong> Same model, different agents. Same agent, different models. Different timeouts, concurrency levels, thinking modes. The goal is to understand <em>what matters</em>&nbsp;&ndash; not just <em>what scored highest in one particular instance</em>.</li>
            <li><strong>Multi-run methodology:</strong> A single run is statistically meaningless&nbsp;&ndash; variance can swing results widely. We run multiple replicates per configuration to get stable, trustworthy numbers.</li>
            <li><strong>Transparency:</strong> Every run is collected, classified, and curated with full metadata: tokens consumed, cache hit rates, duration, timeout, concurrency, agent version, thinking mode, etc. Nothing is hidden.</li>
        </ul>

        <h3>The Five-Metric Framework</h3>
        <p><strong>Performance is a distribution, not a point.</strong> One number can&rsquo;t capture what an AI agent is truly capable of. Five numbers get a lot closer.</p>

        <div class="metric-block">
            <h3>&#9733; Ceiling: <em>What&rsquo;s theoretically possible?</em></h3>
            <p>The union of all tasks ever solved across all runs. If the model solved task A in run 3 and task B in run 5 (but never both in the same run), both count toward the ceiling.</p>
            <p>It tells you the theoretical maximum performance this model is <em>capable of</em> with a given agent&nbsp;&ndash; even if no single run achieves it. It reveals variance-limited tasks: solvable, but not reliably.</p>
        </div>

        <div class="metric-block">
            <h3>&#9650; Best-of: <em>What&rsquo;s the peak in a single run?</em></h3>
            <p>The highest score from any individual run.</p>
            <p>This is the &ldquo;marketing number&rdquo;&nbsp;&ndash; but with context. The closer the best-of is to the average, the more <em>consistent</em> the model performs. A large gap between best-of and average means you&rsquo;re rolling dice every time you run it.</p>
        </div>

        <div class="metric-block">
            <h3>&empty; Average: <em>What can you normally expect?</em></h3>
            <p>The mean score across all valid runs.</p>
            <p>This is the most commonly reported metric&nbsp;&ndash; and it <em>is</em> useful, but only with enough runs to be stable. With a single run? It&rsquo;s a coin flip.</p>
        </div>

        <div class="metric-block">
            <h3>&#9660; Worst-of: <em>How bad can a single run get?</em></h3>
            <p>The lowest score from any individual run.</p>
	            <p>This is the opposite of best-of&nbsp;&ndash; the floor, the worst case. The gap between worst-of and best-of defines the full <em>score range</em> across all runs. A narrow range means predictable performance; a wide range means you&rsquo;re rolling dice.</p>
        </div>

        <div class="metric-block">
            <h3>&#9632; Solid: <em>What does it always get right?</em></h3>
            <p>Tasks that the model solves across all runs&nbsp;&ndash; the rock-solid base with zero variance.</p>
            <p>The higher the solid base, the more <em>dependable</em> the agent is. These are the tasks you can confidently delegate and expect success every time. A model with a high solid base and moderate average is often more reliable in practice than one with a high average but low solid base&nbsp;&ndash; because you know what you&rsquo;re getting.</p>
        </div>

        <h3>Reading the Chart</h3>
	        <p>The five metrics are shown for each model/configuration as stacked bar segments from the rock-solid base up to the ceiling. Optional 3D modes add token volume, run cost, or both as depth: token mode splits input tokens in front and output tokens behind, cost mode uses the total cost for depth, and the combined mode adds a neutral gray cost shadow behind the token-depth bar. The <em>spread</em> between the segments tells you as much as the numbers themselves:</p>
        <ul class="spread-list">
            <li><strong>Tight spread</strong> (metrics close together) = consistent, predictable AI agent</li>
            <li><strong>Wide spread</strong> (big gap between solid and ceiling) = high variance, unreliable</li>
            <li><strong>High ceiling, low average</strong> = the model <em>can</em> do it, but usually doesn&rsquo;t&nbsp;&ndash; needs more runs or better settings</li>
            <li><strong>High solid, close to average</strong> = rock-solid workhorse you can count on</li>
        </ul>

        <h3>The Bottom Line</h3>
        <p>Performance is more complex than a single average score&nbsp;&ndash; and the decisions you make based on benchmarks deserve better data than that. <strong>WolfBench</strong> gives you five angles on every model and configuration, so you can form a more complete and realistic judgement of what an AI agent will actually deliver when you put it to work.</p>
        <p>Because at the end of the day, you don&rsquo;t just want to know which model <em>scored</em> the highest. You want to know which one you can <em>trust</em>.</p>

        <h3>What&rsquo;s Next</h3>
        <p>We will continuously add models and agents to the chart, publish the traces and evals on <a href="https://wandb.ai/wolfram-evals/wolfbench">W&amp;B Weave</a>, and release regular blog posts detailing interesting and insightful findings.</p>
        <p>This benchmark offers enormous potential for discovery. For instance: Why does xhigh reasoning improve GPT 5.4&rsquo;s performance while max effort degrades Opus 4.6&rsquo;s results? How does Claude Code fare when running a GPT or Gemini model compared to running directly with Opus or Sonnet&nbsp;&ndash; or Codex with Claude or Gemini? Is a &ldquo;cheap&rdquo; model actually cost-effective if it consumes far more tokens than a more expensive alternative? How does quantization affect performance of local models in agentic tasks?</p>
        <p>So many possibilities for analysis&nbsp;&ndash; and for posting about it! <em>Stay tuned</em>&nbsp;&ndash; and if you want to be the first to know when new results come in, follow me on <a href="https://x.com/WolframRvnwlf">X</a> and <a href="https://www.linkedin.com/in/wolframravenwolf/">LinkedIn</a>.</p>

        <p class="build-info">Inference and sandbox compute sponsored by <a href="https://www.coreweave.com/">CoreWeave</a>: The Essential Cloud for AI.<br>Additional sandbox compute by <a href="https://www.daytona.io/">Daytona</a>&nbsp;&ndash; Secure Infrastructure for Running AI-Generated Code.<br>Built with <a href="https://harborframework.com/">Harbor</a> for orchestration, <a href="https://www.tbench.ai/">Terminal-Bench 2.0</a> for tasks, and <a href="https://wandb.ai/">W&amp;B Weave</a> for tracking.<br>Charts and dashboards generated with <a href="https://marimo.io/">marimo</a> notebooks.<br>Explore the complete data and tooling suite on our <a href="https://github.com/wandb/WolfBench">WolfBench GitHub</a>.</p>
    </div>
</div>
<script>
{all_js}
</script>
<script type="module">
{three_bars_js}
</script>
</body>
</html>'''

    html = "\n".join(line.rstrip() for line in html.splitlines()) + "\n"
    out = output_path.with_suffix(".html")
    out.write_text(html)
    print(f"Saved: {out}")
    return out


def main():
    parser = argparse.ArgumentParser(
        description="WolfBench Chart — HTML chart generator",
    )
    parser.add_argument(
        "-i", "--input", type=Path,
        default=Path(__file__).parent / "wolfbench_results.json",
    )
    parser.add_argument(
        "-o", "--output", type=Path,
        default=Path(__file__).parent / "wolfbench",
    )
    parser.add_argument("--min-runs", type=int, default=1)
    parser.add_argument(
        "--date", type=str, default=None,
        help="Chart date (YYYY-MM-DD). Defaults to today.",
    )
    parser.add_argument(
        "--weave-manifest", type=Path, default=None,
        help="Path to weave_manifest.json for embedding Weave links in bars.",
    )
    args = parser.parse_args()
    args.chart_date = args.date or date.today().isoformat()

    with open(args.input) as f:
        data = json.load(f)
    print(f"Loaded {data['n_runs']} valid runs from {args.input}")

    run_groups: dict[tuple[str, str, str, float | None, str], list[dict]] = defaultdict(list)
    agent_versions: dict[str, set[str]] = defaultdict(set)
    for r in data["runs"]:
        ver = _resolve_version(r)
        if ver == "-":
            ver = "unknown"
        thinking = _resolve_thinking(r)
        run_groups[(r["agent"], ver, _resolve_display_name(r), r.get("timeout_sec"), thinking)].append(r)
        if ver != "unknown":
            agent_versions[r["agent"]].add(ver)

    metrics = {}
    for key, runs in sorted(run_groups.items(), key=lambda x: (x[0][0], x[0][1], x[0][2], x[0][3] or 0, x[0][4])):
        m = compute_metrics(runs)
        if m:
            metrics[key] = m
            agent, ver, model, _timeout, _thinking = key
            thinking_tag = f" \U0001f9e0{_thinking}" if _thinking != "-" else ""
            print(f"  {agent:>12} v{ver:<14} {model:>20}{thinking_tag}  {m['n_runs']}R  "
                  f"worst={m['min']}%  solid={m['solid_abs']:>2}  avg={m['average']}%  "
                  f"best={m['best']}%  ceil={m['ceiling_abs']:>2}")

    weave_urls = None
    weave_run_urls = None
    if args.weave_manifest and args.weave_manifest.exists():
        try:
            import importlib
            _ww = importlib.import_module("wolfbench_weave")
            weave_urls = _ww.get_evaluation_urls(args.weave_manifest)
            weave_run_urls = _ww.get_run_urls(args.weave_manifest)
        except Exception as e:
            print(f"Warning: could not load weave manifest: {e}")

    generate_html(metrics, args.output, min_runs=args.min_runs,
                  agent_versions=dict(agent_versions),
                  chart_date=args.chart_date,
                  runs=data["runs"],
                  weave_urls=weave_urls,
                  weave_run_urls=weave_run_urls)


if __name__ == "__main__":
    main()
