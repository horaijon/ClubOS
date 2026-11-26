"""Canvas — Autonomous Event Poster Studio Agent.

Generates theme-aware, publication-ready event posters with live event metadata
(date, venue, registration deadline, sponsors, tracks, scannable QR code),
supports iterative prompt-based revisions via Gemini or deterministic fallback,
and handles user-uploaded posters as either style references or final overrides.
"""

from html import escape
import base64
import io
import json
import logging
import os
import re
from typing import Literal

import httpx
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from . import auth, db, intelligence
from .registration import form_for_event
from .state import get_event, now

logger = logging.getLogger(__name__)

POSTER_SCHEMA = """
CREATE TABLE IF NOT EXISTS posters (
    id          TEXT PRIMARY KEY,
    event_id    TEXT NOT NULL REFERENCES events ON DELETE CASCADE,
    title       TEXT NOT NULL,
    kind        TEXT NOT NULL CHECK(kind IN ('generated','reference','final')),
    prompt      TEXT DEFAULT '',
    theme       TEXT DEFAULT '',
    design_json TEXT DEFAULT '{}',
    svg_content TEXT DEFAULT '',
    image_data  BLOB,
    mime_type   TEXT DEFAULT 'image/svg+xml',
    is_active   INTEGER DEFAULT 0,
    created_by  TEXT DEFAULT 'Canvas',
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_posters_event ON posters(event_id, created_at);
"""


class PosterDesign(BaseModel):
    theme_name: str = Field(default="Cobalt Summit", max_length=80)
    visual_motif: Literal["circuit", "grid", "orbital", "geometric", "waves", "robotic", "retro"] = "circuit"
    bg_color: str = Field(default="#0B1437", max_length=20)
    surface_color: str = Field(default="#132152", max_length=20)
    primary_color: str = Field(default="#2563EB", max_length=20)
    accent_color: str = Field(default="#D3FA57", max_length=20)
    text_color: str = Field(default="#FFFFFF", max_length=20)
    muted_color: str = Field(default="#CBD5E1", max_length=20)
    badge_text: str = Field(default="FEATURED CAMPUS EVENT", max_length=60)
    headline: str = Field(default="CodeStorm 2026", max_length=90)
    subheadline: str = Field(default="24-Hour Student Innovation & Builder Showcase", max_length=160)
    date_label: str = Field(default="Date TBA", max_length=80)
    venue_label: str = Field(default="Campus Auditorium", max_length=100)
    deadline_label: str = Field(default="Register early", max_length=80)
    prize_or_highlight: str = Field(default="Open to Student Builders", max_length=90)
    tracks: list[str] = Field(default_factory=list, max_length=5)
    cta_text: str = Field(default="Scan QR to Register", max_length=70)
    footer_note: str = Field(default="", max_length=140)


_THEME_PRESETS: dict[str, dict[str, str]] = {
    "robotic": {
        "theme_name": "Robotic Blueprint",
        "visual_motif": "robotic",
        "bg_color": "#0A0F14",
        "surface_color": "#111C24",
        "primary_color": "#06B6D4",
        "accent_color": "#F59E0B",
        "text_color": "#F0F9FF",
        "muted_color": "#94A3B8",
    },
    "cyber": {
        "theme_name": "Cyber Neon",
        "visual_motif": "circuit",
        "bg_color": "#090B16",
        "surface_color": "#13172D",
        "primary_color": "#8B5CF6",
        "accent_color": "#D3FA57",
        "text_color": "#F8FAFC",
        "muted_color": "#94A3B8",
    },
    "retro": {
        "theme_name": "Retro Synthwave",
        "visual_motif": "retro",
        "bg_color": "#160824",
        "surface_color": "#240F38",
        "primary_color": "#EC4899",
        "accent_color": "#22D3EE",
        "text_color": "#FDF4FF",
        "muted_color": "#E9D5FF",
    },
    "emerald": {
        "theme_name": "Emerald Lab",
        "visual_motif": "grid",
        "bg_color": "#061914",
        "surface_color": "#0D2B22",
        "primary_color": "#10B981",
        "accent_color": "#A7F3D0",
        "text_color": "#ECFDF5",
        "muted_color": "#6EE7B7",
    },
    "minimal": {
        "theme_name": "Swiss Minimal",
        "visual_motif": "geometric",
        "bg_color": "#F8FAFC",
        "surface_color": "#FFFFFF",
        "primary_color": "#1D4ED8",
        "accent_color": "#0F172A",
        "text_color": "#0F172A",
        "muted_color": "#475569",
    },
    "sunset": {
        "theme_name": "Solar Sunset",
        "visual_motif": "waves",
        "bg_color": "#1A0E17",
        "surface_color": "#2A1624",
        "primary_color": "#F97316",
        "accent_color": "#FACC15",
        "text_color": "#FFF7ED",
        "muted_color": "#FDBA74",
    },
    "crimson": {
        "theme_name": "Crimson Forge",
        "visual_motif": "geometric",
        "bg_color": "#17090D",
        "surface_color": "#281118",
        "primary_color": "#EF4444",
        "accent_color": "#FDE047",
        "text_color": "#FEF2F2",
        "muted_color": "#FCA5A5",
    },
    "space": {
        "theme_name": "Deep Space",
        "visual_motif": "orbital",
        "bg_color": "#050816",
        "surface_color": "#0F1633",
        "primary_color": "#6366F1",
        "accent_color": "#38BDF8",
        "text_color": "#F8FAFC",
        "muted_color": "#A5B4FC",
    },
    "cobalt": {
        "theme_name": "Cobalt Summit",
        "visual_motif": "orbital",
        "bg_color": "#0B1437",
        "surface_color": "#132152",
        "primary_color": "#2563EB",
        "accent_color": "#D3FA57",
        "text_color": "#FFFFFF",
        "muted_color": "#CBD5E1",
    },
}


def _hex(rgb: tuple[int, int, int]) -> str:
    return f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"


def _luminance(rgb: tuple[int, int, int]) -> float:
    return 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]


def _contrast_text(bg_hex: str) -> str:
    h = bg_hex.lstrip("#")
    if len(h) == 6:
        try:
            r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
            return "#0F172A" if _luminance((r, g, b)) > 140 else "#FFFFFF"
        except ValueError:
            pass
    return "#0F172A"


def extract_palette_from_image(image_bytes: bytes) -> dict[str, str] | None:
    """Extract dominant background, primary, and accent colors from an uploaded image."""
    try:
        from PIL import Image

        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        img.thumbnail((96, 96))
        quantized = img.quantize(colors=6, method=Image.Quantize.MEDIANCUT).convert("RGB")
        counts = sorted(quantized.getcolors(96 * 96) or [], reverse=True)
        if not counts:
            return None
        colors = [rgb for _, rgb in counts]
        bg = colors[0]
        is_dark = _luminance(bg) < 128

        def saturation(rgb):
            return max(rgb) - min(rgb)

        vivid = sorted(colors[1:] or colors, key=saturation, reverse=True)
        primary = vivid[0]
        accent = vivid[1] if len(vivid) > 1 else (
            (211, 250, 87) if is_dark else (15, 23, 42)
        )
        surface = tuple(
            min(255, c + 16) if is_dark else max(0, c - 10) for c in bg
        )
        return {
            "theme_name": "Reference Palette",
            "bg_color": _hex(bg),
            "surface_color": _hex(surface),
            "primary_color": _hex(primary),
            "accent_color": _hex(accent),
            "text_color": "#F8FAFC" if is_dark else "#0F172A",
            "muted_color": "#CBD5E1" if is_dark else "#475569",
        }
    except Exception:
        return None


def _default_tracks(event: dict) -> list[str]:
    text = " ".join(
        str(event.get(k, "")) for k in ("goals", "description", "type", "requirements")
    ).lower()
    found: list[str] = []
    if "ai" in text or "agent" in text:
        found.append("AI & Agents")
    if "robot" in text or "mech" in text or "drone" in text:
        found.append("Robotics & Autonomy")
    if "access" in text:
        found.append("Accessibility")
    if "hardware" in text or "iot" in text:
        found.append("Hardware & IoT")
    if "campus" in text or "student" in text:
        found.append("Campus Tools")
    if "web" in text or "cloud" in text:
        found.append("Web & Cloud")
    if not found:
        found = [event.get("type", "Innovation")[:24], "Open Track", "Live Demos"]
    return found[:4]


def _pick_preset(text: str) -> tuple[dict[str, str], bool]:
    low = text.lower()
    checks = [
        (("robot", "mecha", "hardware", "drone", "bot", "cyborg", "mech", "industrial", "cyan"), "robotic"),
        (("retro", "synth", "80s", "arcade", "pixel", "vapor", "pink", "magenta"), "retro"),
        (("space", "cosmos", "galaxy", "star", "astro", "universe", "indigo"), "space"),
        (("red", "crimson", "maroon", "gaming", "esport", "arena"), "crimson"),
        (("minimal", "white", "light", "clean", "swiss", "editorial", "pastel"), "minimal"),
        (("emerald", "green", "eco", "mint", "nature", "bio"), "emerald"),
        (("sunset", "orange", "gold", "warm", "fire", "amber", "yellow"), "sunset"),
        (("cyber", "neon", "purple", "violet", "dark", "night", "hacker"), "cyber"),
        (("cobalt", "blue", "ocean", "summit"), "cobalt"),
    ]
    for keywords, key in checks:
        if any(w in low for w in keywords):
            return dict(_THEME_PRESETS[key]), True
    return dict(_THEME_PRESETS["cobalt"]), False


def _apply_prompt_overrides(design: PosterDesign, prompt: str) -> PosterDesign:
    if not prompt.strip():
        return design
    low = prompt.lower()
    preset, matched = _pick_preset(prompt)
    if matched:
        for k, v in preset.items():
            setattr(design, k, v)
    elif "theme" in low or "style" in low or "vibe" in low:
        # Unknown named theme: deterministically pick a fresh palette distinct from current
        keys = [k for k, p in _THEME_PRESETS.items() if p["theme_name"] != design.theme_name]
        chosen = _THEME_PRESETS[keys[sum(ord(ch) for ch in prompt) % len(keys)]]
        for k, v in chosen.items():
            setattr(design, k, v)
        m = re.search(r"(?:theme|style|vibe)\s*(?:to|as|:)?\s*([a-z0-9 &\-]{3,32})", prompt, re.I)
        if m:
            design.theme_name = m.group(1).strip().title()

    if "robot" in low or "mech" in low or "drone" in low:
        design.visual_motif = "robotic"
        design.theme_name = "Robotic Blueprint"
    elif "retro" in low or "synth" in low or "arcade" in low:
        design.visual_motif = "retro"
    elif "grid" in low:
        design.visual_motif = "grid"
    elif "wave" in low:
        design.visual_motif = "waves"
    elif "orbit" in low or "space" in low or "circle" in low:
        design.visual_motif = "orbital"
    elif "geometric" in low or "triangle" in low:
        design.visual_motif = "geometric"
    elif "circuit" in low or "cyber" in low:
        design.visual_motif = "circuit"

    prize = re.search(r"(?:prize(?:\s+pool)?|worth|win)\s*(?:of|:)?\s*(₹\s?[\d,]+(?:\s?[kKlL])?|INR\s?[\d,]+)", prompt, re.I)
    if prize:
        design.prize_or_highlight = f"Prize Pool: {prize.group(1).strip()}"

    quoted = re.search(r'(?:headline|title)\s*(?:to|as|:)?\s*["\']([^"\']{3,70})["\']', prompt, re.I)
    if quoted:
        design.headline = quoted.group(1).strip()

    sub_q = re.search(r'(?:tagline|subtitle|subheadline)\s*(?:to|as|:)?\s*["\']([^"\']{4,120})["\']', prompt, re.I)
    if sub_q:
        design.subheadline = sub_q.group(1).strip()

    tracks_m = re.search(r"tracks?\s*(?:to|as|:)?\s*([A-Za-z0-9 &,/+-]{4,90})", prompt, re.I)
    if tracks_m:
        parts = [t.strip() for t in re.split(r",|\band\b|/", tracks_m.group(1)) if t.strip()]
        if parts:
            design.tracks = parts[:4]

    dl = re.search(r"(?:reg(?:istration)?\s*(?:closes|deadline)|apply by)\s*[:\-]?\s*([A-Za-z0-9 ,\-]{4,28})", prompt, re.I)
    if dl:
        design.deadline_label = "Reg closes " + dl.group(1).strip(" .")

    return design


def _qr_svg_paths(url: str, x: float, y: float, size: float, fg: str) -> str:
    """Render crisp vector QR modules directly inside our SVG poster."""
    try:
        from reportlab.graphics import renderSVG
        from reportlab.graphics.barcode.qr import QrCodeWidget
        from reportlab.graphics.shapes import Drawing

        sz = int(size)
        drawing = Drawing(sz, sz)
        drawing.add(QrCodeWidget(url, barWidth=sz, barHeight=sz))
        raw_svg = renderSVG.drawToString(drawing)
        inner = re.sub(r"^.*?<svg[^>]*>|</svg>\s*$", "", raw_svg, flags=re.S)
        inner = inner.replace("#000000", fg).replace("rgb(0,0,0)", fg).replace("rgb(0%,0%,0%)", fg)
        return f'<svg x="{x}" y="{y}" width="{sz}" height="{sz}" viewBox="0 0 {sz} {sz}">{inner}</svg>'
    except Exception:
        return ""


def _wrap_lines(text: str, max_chars: int, max_lines: int = 2) -> list[str]:
    words = (text or "").split()
    lines: list[str] = []
    curr = ""
    for word in words:
        candidate = (curr + " " + word).strip()
        if len(candidate) <= max_chars:
            curr = candidate
        else:
            if curr:
                lines.append(curr)
            curr = word
            if len(lines) >= max_lines:
                break
    if curr and len(lines) < max_lines:
        lines.append(curr)
    return lines or [text[:max_chars]]


def render_poster_svg(
    design: PosterDesign,
    event: dict,
    sponsors: list[str],
    registration_url: str | None = None,
    bg_image_b64: str | None = None,
    bg_image_mime: str = "image/jpeg",
) -> str:
    """Render a 1080×1350 vector poster SVG (optionally layered over real AI-generated artwork)."""
    W, H = 1080, 1350
    bg = escape(design.bg_color)
    surf = escape(design.surface_color)
    prim = escape(design.primary_color)
    acc = escape(design.accent_color)
    txt = escape(design.text_color)
    muted = escape(design.muted_color)
    acc_ink = _contrast_text(design.accent_color)

    motif_svg = ""
    if design.visual_motif == "robotic":
        lines = "".join(f'<line x1="{x}" y1="0" x2="{x}" y2="{H}"/>' for x in range(80, W, 100))
        hlines = "".join(f'<line x1="0" y1="{y}" x2="{W}" y2="{y}"/>' for y in range(80, H, 100))
        motif_svg = f"""
        <g opacity="0.09" stroke="{prim}" stroke-width="1">{lines}{hlines}</g>
        <g opacity="0.28" stroke="{prim}" stroke-width="2.5" fill="none">
          <polygon points="860,145 965,205 965,325 860,385 755,325 755,205"/>
          <polygon points="860,180 935,223 935,307 860,350 785,307 785,223" stroke="{acc}" stroke-dasharray="10 6"/>
          <circle cx="860" cy="265" r="34" stroke="{acc}"/>
          <circle cx="860" cy="265" r="8" fill="{acc}" stroke="none"/>
          <path d="M720 265 H755 M965 265 H1010 M860 110 V145 M860 385 V420"/>
          <path d="M60 175 H95 V210 M1020 175 H985 V210 M60 760 H95 V725 M1020 760 H985 V725" stroke="{acc}"/>
        </g>"""
    elif design.visual_motif == "retro":
        persp = "".join(f'<line x1="540" y1="740" x2="{x}" y2="{H}"/>' for x in range(-200, 1400, 140))
        motif_svg = f"""
        <g opacity="0.24" stroke="{prim}" stroke-width="2" fill="none">
          <circle cx="850" cy="250" r="145" fill="{prim}" fill-opacity="0.16" stroke="{acc}"/>
          <line x1="705" y1="230" x2="995" y2="230" stroke="{bg}" stroke-width="6"/>
          <line x1="715" y1="265" x2="985" y2="265" stroke="{bg}" stroke-width="8"/>
          <line x1="735" y1="300" x2="965" y2="300" stroke="{bg}" stroke-width="10"/>
          {persp}
        </g>"""
    elif design.visual_motif == "circuit":
        motif_svg = f"""
        <g opacity="0.25" stroke="{prim}" stroke-width="2.5" fill="none">
          <path d="M0 240 H260 L320 300 H640 L700 240 H1080"/>
          <path d="M0 1090 H320 L380 1030 H760 L820 1090 H1080"/>
          <circle cx="260" cy="240" r="6" fill="{acc}" stroke="none"/>
          <circle cx="700" cy="240" r="6" fill="{acc}" stroke="none"/>
          <circle cx="380" cy="1030" r="6" fill="{acc}" stroke="none"/>
          <circle cx="880" cy="180" r="190" stroke="{prim}" stroke-dasharray="10 12" opacity="0.5"/>
        </g>"""
    elif design.visual_motif == "orbital":
        motif_svg = f"""
        <g opacity="0.24" fill="none" stroke="{prim}" stroke-width="2">
          <circle cx="860" cy="240" r="250"/>
          <circle cx="860" cy="240" r="170" stroke="{acc}" stroke-dasharray="8 10"/>
          <circle cx="160" cy="1120" r="220"/>
        </g>"""
    elif design.visual_motif == "grid":
        lines = "".join(f'<line x1="{x}" y1="0" x2="{x}" y2="{H}"/>' for x in range(90, W, 90))
        hlines = "".join(f'<line x1="0" y1="{y}" x2="{W}" y2="{y}"/>' for y in range(90, H, 90))
        motif_svg = f'<g opacity="0.11" stroke="{prim}" stroke-width="1">{lines}{hlines}</g>'
    elif design.visual_motif == "waves":
        motif_svg = f"""
        <g opacity="0.24" fill="none" stroke="{prim}" stroke-width="3">
          <path d="M0 280 Q 270 180 540 280 T 1080 280"/>
          <path d="M0 330 Q 270 230 540 330 T 1080 330" stroke="{acc}" opacity="0.65"/>
          <path d="M0 1080 Q 270 980 540 1080 T 1080 1080"/>
        </g>"""
    else:
        motif_svg = f"""
        <g opacity="0.2" fill="{prim}">
          <polygon points="820,40 1040,40 1040,260"/>
          <rect x="60" y="1060" width="160" height="160" rx="24" fill="none" stroke="{acc}" stroke-width="3"/>
        </g>"""

    # Dynamic vertical rhythm so headline, subheadline, pill, and tracks never overlap
    headline_lines = _wrap_lines(design.headline, 18, 2)
    head_size = 76 if len(headline_lines) == 2 else 84
    head_step = 86 if len(headline_lines) == 2 else 94
    head_y = 265
    headline_svg = "".join(
        f'<text x="80" y="{head_y + i * head_step}" font-family="Inter, -apple-system, BlinkMacSystemFont, sans-serif" '
        f'font-size="{head_size}" font-weight="800" letter-spacing="-2.2" fill="{txt}">{escape(line)}</text>'
        for i, line in enumerate(headline_lines)
    )

    sub_lines = _wrap_lines(design.subheadline, 46, 2)
    sub_y = head_y + (len(headline_lines) - 1) * head_step + 56
    sub_svg = "".join(
        f'<text x="80" y="{sub_y + i * 36}" font-family="Inter, -apple-system, BlinkMacSystemFont, sans-serif" '
        f'font-size="27" font-weight="500" fill="{muted}">{escape(line)}</text>'
        for i, line in enumerate(sub_lines)
    )

    highlight_y = sub_y + (len(sub_lines) - 1) * 36 + 34
    highlight_w = min(920, max(320, len(design.prize_or_highlight) * 14 + 54))

    tracks = design.tracks or _default_tracks(event)
    track_chips = ""
    tx = 80
    ty = highlight_y + 72
    for tr in tracks[:4]:
        w = max(130, len(tr) * 14 + 44)
        if tx + w > 1000:
            tx = 80
            ty += 56
        track_chips += (
            f'<rect x="{tx}" y="{ty}" width="{w}" height="44" rx="22" fill="{surf}" stroke="{prim}" stroke-opacity="0.55" stroke-width="1.5"/>'
            f'<text x="{tx + w / 2}" y="{ty + 28}" text-anchor="middle" font-family="Inter, sans-serif" font-size="20" font-weight="600" fill="{txt}">{escape(tr)}</text>'
        )
        tx += w + 14

    sponsor_str = " · ".join(sponsors[:4]) if sponsors else "Student Technical Community"
    club_label = escape(f"{event.get('club', 'ClubOS')} · {event.get('college', '')}".strip(" ·"))

    qr_block = ""
    if registration_url:
        qr_inner = _qr_svg_paths(registration_url, 816, 1084, 152, "#0F172A")
        qr_block = f"""
        <rect x="800" y="1068" width="184" height="184" rx="16" fill="#FFFFFF"/>
        {qr_inner}
        """

    ai_bg_layer = ""
    card_opacity = ' fill-opacity="0.82"' if bg_image_b64 else ""
    if bg_image_b64:
        ai_bg_layer = f"""
  <image href="data:{escape(bg_image_mime)};base64,{bg_image_b64}" x="0" y="0" width="{W}" height="{H}" preserveAspectRatio="xMidYMid slice"/>
  <rect width="{W}" height="{H}" fill="url(#scrim)"/>"""

    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}">
  <defs>
    <radialGradient id="glow" cx="80%" cy="18%" r="65%">
      <stop offset="0%" stop-color="{prim}" stop-opacity="0.34"/>
      <stop offset="100%" stop-color="{bg}" stop-opacity="0"/>
    </radialGradient>
    <linearGradient id="scrim" x1="0%" y1="0%" x2="0%" y2="100%">
      <stop offset="0%" stop-color="#070B14" stop-opacity="0.62"/>
      <stop offset="45%" stop-color="#070B14" stop-opacity="0.45"/>
      <stop offset="100%" stop-color="#070B14" stop-opacity="0.88"/>
    </linearGradient>
  </defs>
  <rect width="{W}" height="{H}" fill="{bg}"/>
  <rect width="{W}" height="{H}" fill="url(#glow)"/>
  {ai_bg_layer}
  {motif_svg}

  <!-- Top Organizer Pill -->
  <rect x="80" y="76" width="920" height="58" rx="29" fill="{surf}"{card_opacity} stroke="{prim}" stroke-opacity="0.38"/>
  <circle cx="114" cy="105" r="8" fill="{acc}"/>
  <text x="136" y="113" font-family="Inter, sans-serif" font-size="22" font-weight="700" fill="{txt}">{club_label[:48]}</text>
  <text x="970" y="113" text-anchor="end" font-family="Inter, sans-serif" font-size="18" font-weight="700" letter-spacing="1.5" fill="{acc}">{escape(design.badge_text.upper()[:28])}</text>

  <!-- Main Headline & Subheadline -->
  {headline_svg}
  {sub_svg}

  <!-- Highlight Pill -->
  <rect x="80" y="{highlight_y}" width="{highlight_w}" height="48" rx="12" fill="{acc}"/>
  <text x="104" y="{highlight_y + 32}" font-family="Inter, sans-serif" font-size="22" font-weight="800" fill="{acc_ink}">{escape(design.prize_or_highlight[:54])}</text>

  <!-- Tracks -->
  {track_chips}

  <!-- Event Details Grid -->
  <rect x="80" y="790" width="446" height="122" rx="18" fill="{surf}"{card_opacity} stroke="{prim}" stroke-opacity="0.35"/>
  <text x="110" y="832" font-family="Inter, sans-serif" font-size="17" font-weight="700" letter-spacing="1.2" fill="{acc}">DATE &amp; SCHEDULE</text>
  <text x="110" y="878" font-family="Inter, sans-serif" font-size="27" font-weight="700" fill="{txt}">{escape(design.date_label[:30])}</text>

  <rect x="554" y="790" width="446" height="122" rx="18" fill="{surf}"{card_opacity} stroke="{prim}" stroke-opacity="0.35"/>
  <text x="584" y="832" font-family="Inter, sans-serif" font-size="17" font-weight="700" letter-spacing="1.2" fill="{acc}">VENUE</text>
  <text x="584" y="878" font-family="Inter, sans-serif" font-size="27" font-weight="700" fill="{txt}">{escape(design.venue_label[:28])}</text>

  <rect x="80" y="932" width="446" height="104" rx="18" fill="{surf}"{card_opacity} stroke="{prim}" stroke-opacity="0.35"/>
  <text x="110" y="970" font-family="Inter, sans-serif" font-size="16" font-weight="700" letter-spacing="1.2" fill="{muted}">REGISTRATION</text>
  <text x="110" y="1008" font-family="Inter, sans-serif" font-size="24" font-weight="700" fill="{txt}">{escape(design.deadline_label[:30])}</text>

  <rect x="554" y="932" width="446" height="104" rx="18" fill="{surf}"{card_opacity} stroke="{prim}" stroke-opacity="0.35"/>
  <text x="584" y="970" font-family="Inter, sans-serif" font-size="16" font-weight="700" letter-spacing="1.2" fill="{muted}">CAPACITY &amp; FORMAT</text>
  <text x="584" y="1008" font-family="Inter, sans-serif" font-size="24" font-weight="700" fill="{txt}">{event.get('target', 100)} Builders · {escape(str(event.get('type', 'Event'))[:18])}</text>

  <!-- Footer CTA & QR Banner -->
  <rect x="80" y="1054" width="920" height="214" rx="22" fill="{surf}"{card_opacity} stroke="{acc}" stroke-opacity="0.45" stroke-width="2"/>
  <text x="116" y="1114" font-family="Inter, sans-serif" font-size="32" font-weight="800" fill="{txt}">{escape(design.cta_text[:34])}</text>
  <text x="116" y="1158" font-family="Inter, sans-serif" font-size="21" font-weight="500" fill="{muted}">Supported by: {escape(sponsor_str[:56])}</text>
  <text x="116" y="1216" font-family="Inter, sans-serif" font-size="18" font-weight="600" fill="{acc}">{escape((registration_url or design.footer_note or 'Register via ClubOS')[:62])}</text>
  {qr_block}
</svg>"""


def _build_design(
    c,
    event: dict,
    prompt: str = "",
    base_design: dict | None = None,
    reference_bytes: bytes | None = None,
    reference_mime: str | None = None,
) -> tuple[PosterDesign, str]:
    """Generate or revise a PosterDesign using Gemini (with multimodal reference support) or deterministic engine."""
    form = form_for_event(c, event["id"])
    deadline = (form or {}).get("deadline") or event.get("milestone_date") or event["start_date"]
    date_label = (
        f"{event['start_date']} – {event['end_date']}"
        if event.get("end_date") and event["end_date"] != event["start_date"]
        else event["start_date"]
    )

    if base_design:
        fallback = PosterDesign(**base_design)
    else:
        preset, _ = _pick_preset(f"{event.get('type', '')} {event.get('goals', '')} {prompt}")
        fallback = PosterDesign(
            **preset,
            badge_text=f"{event.get('type', 'EVENT').upper()}",
            headline=event["name"],
            subheadline=(event.get("description") or event.get("goals") or "Join us for an unforgettable build experience.")[:150],
            date_label=date_label,
            venue_label=event.get("venue") or "Campus Auditorium",
            deadline_label=f"Closes {deadline}",
            prize_or_highlight=f"{event.get('target', 100)}+ Builders · {event.get('type', 'Event')}",
            tracks=_default_tracks(event),
            cta_text="Scan QR to Register",
            footer_note=f"{event.get('club', '')} · {event.get('college', '')}".strip(" ·"),
        )

    if reference_bytes:
        palette = extract_palette_from_image(reference_bytes)
        if palette:
            for k, v in palette.items():
                setattr(fallback, k, v)

    fallback = _apply_prompt_overrides(fallback, prompt)

    payload = {
        "event": {
            "name": event["name"],
            "type": event.get("type"),
            "description": event.get("description"),
            "goals": event.get("goals"),
            "venue": event.get("venue"),
            "start_date": event["start_date"],
            "end_date": event.get("end_date"),
            "deadline": deadline,
            "target": event.get("target"),
            "college": event.get("college"),
            "club": event.get("club"),
        },
        "current_design": fallback.model_dump(),
        "user_prompt": prompt or "Create an eye-catching event poster aligned with the event theme and details.",
        "available_motifs": ["robotic", "circuit", "retro", "orbital", "grid", "waves", "geometric"],
        "has_reference_poster": bool(reference_bytes),
        "task": (
            "You are updating a PosterDesign JSON based directly on user_prompt. "
            "Apply EVERY instruction in user_prompt: change theme_name, visual_motif (pick best match from available_motifs), "
            "all hex colors (bg_color, surface_color, primary_color, accent_color, text_color, muted_color — keep strong contrast!), "
            "badge_text, headline, subheadline, prize_or_highlight, tracks, cta_text, date_label, venue_label, deadline_label."
        ),
    }

    mode = "Deterministic"
    if os.getenv("GEMINI_API_KEY"):
        try:
            if reference_bytes and reference_mime and reference_mime in ("image/png", "image/jpeg", "image/webp"):
                from google.genai import types
                client = intelligence._client()
                parts = [
                    types.Part.from_bytes(data=reference_bytes, mime_type=reference_mime),
                    json.dumps(payload, ensure_ascii=False),
                ]
                resp = client.models.generate_content(
                    model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
                    contents=parts,
                    config=types.GenerateContentConfig(
                        system_instruction="You are Canvas, an expert event poster designer. Match the reference poster's palette/energy and strictly apply the user_prompt.",
                        response_mime_type="application/json",
                        response_schema=PosterDesign,
                        temperature=0.4,
                    ),
                )
                return PosterDesign.model_validate_json(resp.text), "Gemini Vision"

            from google.genai import types
            client = intelligence._client()
            resp = client.models.generate_content(
                model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
                contents=json.dumps(payload, ensure_ascii=False),
                config=types.GenerateContentConfig(
                    system_instruction="You are Canvas, an expert event poster designer. Transform the poster theme, hex colors, visual_motif, and text fields directly according to user_prompt. Keep high text contrast and accurate event facts.",
                    response_mime_type="application/json",
                    response_schema=PosterDesign,
                    temperature=0.45,
                ),
            )
            return PosterDesign.model_validate_json(resp.text), "Gemini"
        except Exception:
            logger.warning("Gemini poster generation fell back to deterministic theme engine", exc_info=True)

    return fallback, mode


def _raster_image_prompt(event: dict, sponsors: list[str], deadline: str, reg_url: str | None, prompt: str, has_ref: bool, has_base: bool) -> str:
    date_label = (
        f"{event['start_date']} to {event['end_date']}"
        if event.get("end_date") and event["end_date"] != event["start_date"]
        else event["start_date"]
    )
    sponsor_line = ", ".join(sponsors[:4])
    parts = [
        "Design a portrait event poster with crisp, legible typography.",
    ]
    if has_ref and has_base:
        parts.append("The first image is the current poster. The second image is the style reference.")
    if has_ref:
        parts.append("REFERENCE STYLE INSTRUCTION: Use the attached reference for palette, hierarchy, typography mood, composition, and lighting. Create fresh artwork for this event. Do not copy the reference’s names, logos, text, or QR codes.")
    if has_base and prompt:
        parts.append(f"EDIT INSTRUCTION: Modify the attached current poster according to the user's request: {prompt}")
    elif prompt:
        parts.append(f"THEME & PROMPT INSTRUCTION: {prompt}")
    parts.extend([
        "Use these saved event facts as the source of truth. The design prompt and any attached images guide the visuals only. Copy names, dates, and venue exactly. Do not invent sponsors, prizes, URLs, or QR codes.",
        f"- Event Title: {event['name']}",
        f"- Subtitle / Theme: {(event.get('description') or event.get('type') or '')[:140]}",
        f"- Hosted by: {event.get('club', '')} · {event.get('college', '')}".strip(" ·"),
        f"- Date: {date_label}",
        f"- Venue: {event['venue']}",
        f"- Event format: {event['type']}",
        f"- Expected participants: {event['target']}",
        f"- Registration closes: {deadline}",
    ])
    if sponsor_line:
        parts.append(f"- Confirmed sponsors: {sponsor_line}")
    if reg_url:
        parts.append(f"- Registration: {reg_url}. Use a Register Now callout.")
    if event.get("brief_prizes"):
        parts.append(f"- Prizes: {event['brief_prizes']}")
    if event.get("brief_tracks"):
        parts.append(f"- Tracks: {', '.join(event['brief_tracks'])}")
    return "\n".join(parts)


def _provider_failure(provider: str, status: int | None, code: str = "") -> str:
    if code in {"credit_balance_exhausted", "insufficient_quota", "billing_hard_limit_reached"}:
        return f"{provider} image credits are exhausted. Add API credits or use a funded key."
    if status == 429:
        return f"{provider} reached its image quota or rate limit. Check the project quota before retrying."
    if status in (401, 403):
        return f"{provider} denied access. Check the API key and image model permissions."
    if status == 404:
        return f"{provider} image model is unavailable for this project."
    return f"{provider} could not return an image. Try again later."


def _build_free_poster_prompt(
    event: dict,
    sponsors: list[str],
    prompt: str,
    reference_bytes: bytes | None = None,
) -> str:
    palette_hint = ""
    if reference_bytes:
        pal = extract_palette_from_image(reference_bytes)
        if pal:
            palette_hint = (
                f" Strictly match this color palette: background {pal['bg_color']}, "
                f"primary {pal['primary_color']}, accent {pal['accent_color']}."
            )

    style_desc = (prompt or "").strip() or (
        f"Bold modern editorial graphic design for a campus {event.get('type', 'tech event')}"
    )
    tracks = event.get("brief_tracks") or _default_tracks(event)
    mood_context = (event.get("description") or event.get("goals") or "").strip()[:140]
    parts = [
        f"Editorial graphic design event poster. Visual style and concept: {style_desc}.",
        f"Display only the bold event title \"{event['name']}\" cleanly in the upper section, with small event type label \"{event.get('type', 'Event')}\".",
        f"Subject atmosphere inspired by: {mood_context or event.get('type', 'innovation')}, themes {', '.join(tracks[:3])}.{palette_hint}",
        "Leave a clean, uncluttered dark gradient band along the bottom 18% of the frame for an overlaid info card. Do NOT render dates, venue addresses, URLs, QR codes, gibberish small words, or watermarks.",
    ]
    return " ".join(parts)[:1100]


def _load_pil_font(size: int, bold: bool = False):
    from PIL import ImageFont

    candidates = (
        [
            "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
            "/Library/Fonts/Arial Unicode.ttf",
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
        ]
        if bold
        else [
            "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
            "/Library/Fonts/Arial Unicode.ttf",
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
        ]
    )
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _draw_qr_on_image(canvas, url: str, box_x: int, box_y: int, box_size: int) -> None:
    from PIL import ImageDraw
    from reportlab.graphics.barcode.qr import QrCodeWidget

    widget = QrCodeWidget(url)
    widget.draw()
    modules = getattr(getattr(widget, "qr", None), "modules", None)
    if not modules:
        return
    draw = ImageDraw.Draw(canvas, "RGBA")
    draw.rounded_rectangle(
        [box_x, box_y, box_x + box_size, box_y + box_size],
        radius=12,
        fill=(255, 255, 255, 255),
    )
    count = len(modules)
    pad = 10
    inner = box_size - 2 * pad
    cell = inner / count
    for r_idx, row in enumerate(modules):
        for c_idx, dark in enumerate(row):
            if dark:
                x0 = box_x + pad + c_idx * cell
                y0 = box_y + pad + r_idx * cell
                draw.rectangle([x0, y0, x0 + cell + 0.4, y0 + cell + 0.4], fill=(15, 23, 42, 255))


def _composite_verified_event_footer(
    raw_bytes: bytes,
    event: dict,
    sponsors: list[str],
    deadline: str,
    reg_url: str | None,
) -> bytes:
    """Resize generated AI artwork to 1080x1350 and overlay a crisp verified event + QR footer strip."""
    from PIL import Image, ImageDraw, ImageOps

    W, H = 1080, 1350
    with Image.open(io.BytesIO(raw_bytes)) as src:
        img = ImageOps.fit(src.convert("RGBA"), (W, H), method=Image.Resampling.LANCZOS)

    pal = extract_palette_from_image(raw_bytes) or {}
    acc_hex = (pal.get("accent_color") or "#D3FA57").lstrip("#")
    try:
        acc_rgb = (int(acc_hex[0:2], 16), int(acc_hex[2:4], 16), int(acc_hex[4:6], 16))
        if _luminance(acc_rgb) < 110:
            acc_rgb = (211, 250, 87)
    except Exception:
        acc_rgb = (211, 250, 87)

    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay, "RGBA")
    for y in range(1030, H):
        alpha = int(195 * ((y - 1030) / (H - 1030)) ** 1.2)
        odraw.line([(0, y), (W, y)], fill=(7, 11, 20, alpha))

    card_x0, card_y0, card_x1, card_y1 = 44, 1108, W - 44, H - 36
    odraw.rounded_rectangle(
        [card_x0, card_y0, card_x1, card_y1],
        radius=22,
        fill=(10, 15, 29, 250),
        outline=(*acc_rgb, 195),
        width=2,
    )
    img = Image.alpha_composite(img, overlay)

    draw = ImageDraw.Draw(img, "RGBA")
    f_kicker = _load_pil_font(19, bold=True)
    f_main = _load_pil_font(28, bold=True)
    f_meta = _load_pil_font(21, bold=False)
    f_small = _load_pil_font(17, bold=True)

    date_label = (
        f"{event['start_date']} to {event['end_date']}"
        if event.get("end_date") and event["end_date"] != event["start_date"]
        else event["start_date"]
    )
    club_line = f"{event.get('club', 'ClubOS')}  ·  {event.get('college', '')}".strip(" ·").upper()
    venue_line = f"{date_label}   ·   {event.get('venue', 'Campus')}"
    tracks = event.get("brief_tracks") or _default_tracks(event)
    detail_parts = [f"Reg closes {deadline}"]
    if event.get("brief_prizes"):
        prizes_clean = str(event["brief_prizes"]).replace("₹", "INR ")
        detail_parts.append(f"Prizes: {prizes_clean[:36]}")
    elif tracks:
        detail_parts.append(" · ".join(tracks[:2]))
    if sponsors:
        detail_parts.append(f"Sponsors: {', '.join(sponsors[:2])}")
    detail_line = "   |   ".join(detail_parts).replace("₹", "INR ")

    text_x = card_x0 + 28
    draw.text((text_x, card_y0 + 22), club_line[:64], font=f_kicker, fill=(*acc_rgb, 255))
    draw.text((text_x, card_y0 + 54), venue_line[:52], font=f_main, fill=(248, 250, 252, 255))
    draw.text((text_x, card_y0 + 98), detail_line[:74], font=f_meta, fill=(203, 213, 225, 255))

    if reg_url:
        qr_size = 132
        qr_x = card_x1 - qr_size - 22
        qr_y = card_y0 + 20
        _draw_qr_on_image(img, reg_url, qr_x, qr_y, qr_size)
        draw.text((qr_x + 4, qr_y + qr_size + 6), "SCAN TO REGISTER", font=_load_pil_font(12, bold=True), fill=(*acc_rgb, 255))
        draw.text((text_x, card_y0 + 138), reg_url[:58], font=f_small, fill=(*acc_rgb, 230))
    else:
        badge_text = f"{event.get('target', 100)}+ PARTICIPANTS  ·  {event.get('type', 'EVENT').upper()}"
        draw.text((text_x, card_y0 + 138), badge_text[:56], font=f_small, fill=(*acc_rgb, 235))

    out = io.BytesIO()
    img.convert("RGB").save(out, format="PNG")
    return out.getvalue()


def _generate_cloudflare_image(art_prompt: str) -> tuple[bytes | None, str]:
    account_id = os.getenv("CLOUDFLARE_ACCOUNT_ID", "").strip()
    token = os.getenv("CLOUDFLARE_API_TOKEN", "").strip()
    if not account_id or not token:
        return None, ""
    headers = {"Authorization": f"Bearer {token}"}
    for model in (
        "@cf/black-forest-labs/flux-1-schnell",
        "@cf/stabilityai/stable-diffusion-xl-base-1.0",
    ):
        url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{model}"
        payload = {"prompt": art_prompt, "steps": 4} if "flux" in model else {"prompt": art_prompt}
        try:
            resp = httpx.post(url, headers=headers, json=payload, timeout=45.0)
            if not resp.is_success:
                continue
            ctype = resp.headers.get("content-type", "")
            if ctype.startswith("image/") and len(resp.content) > 2000:
                return resp.content, f"Cloudflare {model.split('/')[-1]}"
            data = resp.json()
            b64 = (data.get("result") or {}).get("image")
            if b64:
                return base64.b64decode(b64), f"Cloudflare {model.split('/')[-1]}"
        except Exception:
            logger.debug("Cloudflare Workers AI model %s failed", model, exc_info=True)
    return None, ""


def _generate_hf_flux_image(art_prompt: str) -> tuple[bytes | None, str]:
    import random

    seed = random.randint(1, 999999)
    base = "https://black-forest-labs-flux-1-schnell.hf.space"
    try:
        r = httpx.post(
            f"{base}/gradio_api/call/infer",
            json={"data": [art_prompt, seed, True, 768, 960, 4]},
            timeout=15.0,
        )
        if not r.is_success:
            return None, ""
        eid = r.json().get("event_id")
        if not eid:
            return None, ""
        sse = httpx.get(f"{base}/gradio_api/call/infer/{eid}", timeout=50.0)
        if not sse.is_success:
            return None, ""
        img_url = None
        for line in sse.text.splitlines():
            if line.startswith("data: "):
                try:
                    parsed = json.loads(line[6:])
                    if isinstance(parsed, list) and parsed and isinstance(parsed[0], dict):
                        img_url = parsed[0].get("url")
                except ValueError:
                    continue
        if not img_url:
            return None, ""
        img_resp = httpx.get(img_url, timeout=20.0, follow_redirects=True)
        if img_resp.is_success and len(img_resp.content) > 2000:
            return img_resp.content, "FLUX.1-schnell (Free AI)"
    except Exception:
        logger.debug("HF FLUX.1-schnell generation failed", exc_info=True)
    return None, ""


def _generate_ai_horde_image(art_prompt: str) -> tuple[bytes | None, str]:
    import time

    api_key = os.getenv("AI_HORDE_API_KEY", "").strip() or "0000000000"
    headers = {"apikey": api_key, "Client-Agent": "ClubOS:1.0:poster-studio"}
    try:
        submit = httpx.post(
            "https://aihorde.net/api/v2/generate/async",
            headers=headers,
            json={
                "prompt": art_prompt,
                "params": {"width": 512, "height": 640, "steps": 20, "n": 1},
                "models": ["Deliberate", "stable_diffusion", "ICBINP - I Can't Believe It's Not Photography"],
                "r2": True,
            },
            timeout=10.0,
        )
        if not submit.is_success:
            return None, ""
        job_id = submit.json().get("id")
        if not job_id:
            return None, ""
        for _ in range(12):
            time.sleep(2.0)
            check = httpx.get(f"https://aihorde.net/api/v2/generate/check/{job_id}", timeout=6.0)
            if check.is_success and check.json().get("done"):
                status = httpx.get(f"https://aihorde.net/api/v2/generate/status/{job_id}", timeout=10.0)
                gens = status.json().get("generations") or []
                if gens and gens[0].get("img"):
                    img_url = gens[0]["img"]
                    if img_url.startswith("http"):
                        dl = httpx.get(img_url, timeout=15.0, follow_redirects=True)
                        if dl.is_success and len(dl.content) > 2000:
                            return dl.content, "AI Horde (Free AI)"
                break
    except Exception:
        logger.debug("AI Horde generation failed", exc_info=True)
    return None, ""


def _generate_free_ai_raster_poster(
    event: dict,
    sponsors: list[str],
    deadline: str,
    reg_url: str | None,
    prompt: str,
    reference_bytes: bytes | None = None,
) -> tuple[bytes | None, str]:
    """Generate a bespoke AI poster via Cloudflare Workers AI, HF FLUX.1-schnell, Pollinations, or AI Horde."""
    art_prompt = _build_free_poster_prompt(event, sponsors, prompt, reference_bytes=reference_bytes)

    raw_bytes, provider = _generate_cloudflare_image(art_prompt)
    if not raw_bytes:
        raw_bytes, provider = _generate_hf_flux_image(art_prompt)
    if not raw_bytes:
        # Try Pollinations with optional key or Classic endpoint
        from urllib.parse import quote
        import random

        poll_key = os.getenv("POLLINATIONS_API_KEY", "").strip()
        seed = random.randint(1, 999999)
        if poll_key:
            url = f"https://gen.pollinations.ai/image/{quote(art_prompt[:450])}?width=768&height=960&model=flux&seed={seed}"
            hdrs = {"Authorization": f"Bearer {poll_key}"}
        else:
            url = f"https://image.pollinations.ai/prompt/{quote(art_prompt[:450])}?width=768&height=960&nologo=true&seed={seed}"
            hdrs = {}
        try:
            r = httpx.get(url, headers=hdrs, timeout=20.0, follow_redirects=True)
            if r.status_code == 200 and r.headers.get("content-type", "").startswith("image/") and len(r.content) > 5000:
                raw_bytes, provider = r.content, "Pollinations AI"
        except Exception:
            pass
    if not raw_bytes:
        raw_bytes, provider = _generate_ai_horde_image(art_prompt)
    if not raw_bytes:
        return None, ""

    try:
        composed = _composite_verified_event_footer(raw_bytes, event, sponsors, deadline, reg_url)
        return composed, provider
    except Exception:
        logger.debug("Poster footer composite failed, returning raw image", exc_info=True)
        return raw_bytes, provider


def _fetch_pollinations_background(event: dict, design: PosterDesign, prompt: str) -> tuple[str | None, str]:
    """Generate bespoke AI artwork background via Pollinations when OpenAI/Nano Banana credits are exhausted."""
    from urllib.parse import quote
    import random

    style_bits = prompt.strip() or f"{design.theme_name} {event.get('type', 'tech event')}"
    art_prompt = (
        f"High-craft graphic design poster background artwork for '{event.get('name', 'tech event')}' "
        f"({event.get('type', 'hackathon')}). Visual theme: {style_bits}. "
        f"Color palette: {design.bg_color}, {design.primary_color}, {design.accent_color}. "
        f"Dramatic studio lighting, abstract futuristic depth, clean composition, NO TEXT, NO WORDS, NO LETTERS, NO WATERMARK."
    )
    seed = random.randint(1, 999999)
    url = f"https://image.pollinations.ai/prompt/{quote(art_prompt[:450])}?width=768&height=960&nologo=true&seed={seed}"
    try:
        r = httpx.get(url, timeout=24.0, follow_redirects=True)
        if r.status_code == 200 and r.headers.get("content-type", "").startswith("image/") and len(r.content) > 5000:
            return base64.b64encode(r.content).decode("ascii"), r.headers["content-type"].split(";")[0]
    except Exception:
        logger.debug("Pollinations background fetch failed", exc_info=True)
    return None, "image/jpeg"


def _generate_ai_raster_poster(
    event: dict,
    sponsors: list[str],
    deadline: str,
    reg_url: str | None,
    prompt: str,
    reference_bytes: bytes | None = None,
    reference_mime: str | None = None,
    base_bytes: bytes | None = None,
    base_mime: str | None = None,
    allow_free: bool = True,
) -> tuple[bytes | None, str, str]:
    """Generate poster artwork with OpenAI, Gemini, Cloudflare Workers AI, or free HF FLUX.1-schnell."""
    full_prompt = _raster_image_prompt(
        event, sponsors, deadline, reg_url, prompt,
        has_ref=bool(reference_bytes),
        has_base=bool(base_bytes and prompt),
    )
    errors: list[str] = []

    openai_key = os.getenv("OPENAI_API_KEY", "").strip()
    if openai_key:
        model = "gpt-image-2.5-flare"
        headers = {"Authorization": f"Bearer {openai_key}"}
        params = {"model": model, "prompt": full_prompt, "size": "1024x1536", "quality": "medium"}
        images = []
        for name, data, mime in (("current", base_bytes, base_mime), ("reference", reference_bytes, reference_mime)):
            if data and mime in ("image/png", "image/jpeg", "image/webp"):
                images.append(("image[]", (f"{name}.{mime.split('/')[1]}", data, mime)))
        try:
            if images:
                resp = httpx.post("https://api.openai.com/v1/images/edits", headers=headers,
                                  data=params, files=images, timeout=150.0)
            else:
                resp = httpx.post("https://api.openai.com/v1/images/generations", headers=headers,
                                  json=params, timeout=150.0)
            if resp.is_success:
                return base64.b64decode(resp.json()["data"][0]["b64_json"], validate=True), f"OpenAI {model}", ""
            try:
                code = resp.json().get("error", {}).get("code")
            except ValueError:
                code = None
            errors.append(_provider_failure("OpenAI", resp.status_code, code))
        except Exception:
            errors.append(_provider_failure("OpenAI", None))

    if os.getenv("GEMINI_API_KEY"):
        try:
            from google.genai import types
            client = intelligence._client()
            contents: list = []
            if base_bytes and base_mime in ("image/png", "image/jpeg", "image/webp") and prompt:
                contents.append(types.Part.from_bytes(data=base_bytes, mime_type=base_mime))
            if reference_bytes and reference_mime in ("image/png", "image/jpeg", "image/webp"):
                contents.append(types.Part.from_bytes(data=reference_bytes, mime_type=reference_mime))
            contents.append(full_prompt)

            for model in ("gemini-3.1-flash-image", "gemini-3.1-flash-lite-image"):
                try:
                    resp = client.models.generate_content(
                        model=model,
                        contents=contents,
                        config=types.GenerateContentConfig(response_modalities=["TEXT", "IMAGE"], http_options=types.HttpOptions(timeout=120000)),
                    )
                    for part in resp.candidates[0].content.parts:
                        if part.inline_data and part.inline_data.data:
                            return bytes(part.inline_data.data), f"Nano Banana ({model})", ""
                except Exception as exc:
                    status = getattr(exc, "code", None)
                    errors.append(_provider_failure("Gemini", status))
                    if status in (401, 403):
                        break
        except Exception:
            errors.append(_provider_failure("Gemini", None))

    if allow_free:
        free_png, free_mode = _generate_free_ai_raster_poster(
            event, sponsors, deadline, reg_url, prompt, reference_bytes=reference_bytes
        )
        if free_png:
            return free_png, free_mode, " ".join(dict.fromkeys(errors))

    return None, "", " ".join(dict.fromkeys(errors))


def create_poster_record(
    c,
    event_id: str,
    prompt: str = "",
    reference_poster_id: str | None = None,
    base_poster_id: str | None = None,
    activate: bool = True,
    use_ai_image: bool = True,
    require_ai: bool = False,
) -> dict:
    """Generate a poster for *event_id*, persist it, and optionally set it active."""
    event = get_event(c, event_id)
    saved_brief=c.execute("SELECT details FROM event_briefs WHERE event_id=?",(event_id,)).fetchone()
    if saved_brief:
        facts=json.loads(saved_brief['details'])
        event.update(brief_prizes=facts.get('prizes'),brief_tracks=facts.get('tracks'))
    sponsors = [
        r["name"]
        for r in c.execute(
            """SELECT p.name FROM sponsors s JOIN profiles p ON p.id = s.prospect_id
               WHERE s.event_id=? AND s.stage='Confirmed' ORDER BY s.committed DESC""",
            (event_id,),
        )
    ]
    form = form_for_event(c, event_id)
    deadline = (form or {}).get("deadline") or event.get("milestone_date") or event["start_date"]
    port = os.getenv("PORT", "8018")
    reg_url = (form or {}).get("public_url") or (f"http://127.0.0.1:{port}/register/{form['slug']}" if form and form.get("slug") else None)

    base_design = None
    base_bytes, base_mime = None, None
    if base_poster_id:
        row = c.execute(
            "SELECT design_json, image_data, mime_type FROM posters WHERE id=? AND event_id=?",
            (base_poster_id, event_id),
        ).fetchone()
        if row:
            if row["design_json"]:
                try:
                    base_design = json.loads(row["design_json"])
                except Exception:
                    base_design = None
            if row["image_data"] and row["mime_type"] in ("image/png", "image/jpeg", "image/webp"):
                base_bytes, base_mime = bytes(row["image_data"]), row["mime_type"]

    ref_bytes, ref_mime = None, None
    if reference_poster_id:
        ref = c.execute(
            "SELECT image_data, mime_type FROM posters WHERE id=? AND event_id=?",
            (reference_poster_id, event_id),
        ).fetchone()
        if ref and ref["image_data"]:
            ref_bytes, ref_mime = bytes(ref["image_data"]), ref["mime_type"]
    elif not require_ai:
        ref = c.execute(
            "SELECT image_data, mime_type FROM posters WHERE event_id=? AND kind='reference' ORDER BY rowid DESC LIMIT 1",
            (event_id,),
        ).fetchone()
        if ref and ref["image_data"]:
            ref_bytes, ref_mime = bytes(ref["image_data"]), ref["mime_type"]

    if require_ai:
        if reference_poster_id and (not ref_bytes or ref_mime not in ("image/png","image/jpeg","image/webp")):
            raise HTTPException(422, "Choose a PNG, JPG, or WebP reference from this event.")
        if base_poster_id and not base_bytes:
            raise HTTPException(422, "Choose a raster poster to revise.")
    ai_png = None
    ai_mode = ""
    ai_err = ""
    has_provider_key = bool(
        os.getenv("OPENAI_API_KEY")
        or os.getenv("GEMINI_API_KEY")
        or (os.getenv("CLOUDFLARE_ACCOUNT_ID") and os.getenv("CLOUDFLARE_API_TOKEN"))
    )
    if use_ai_image and (require_ai or has_provider_key):
        ai_png, ai_mode, ai_err = _generate_ai_raster_poster(
            event, sponsors, deadline, reg_url, prompt,
            reference_bytes=ref_bytes, reference_mime=ref_mime,
            base_bytes=base_bytes, base_mime=base_mime,
        )

    if require_ai and not ai_png:
        raise HTTPException(502, ai_err or "The image provider returned no artwork. Try a different prompt.")

    if ai_png:
        from PIL import Image
        from io import BytesIO
        try:
            with Image.open(BytesIO(ai_png)) as image:
                image.load()
                if image.format!="PNG":
                    output=BytesIO()
                    image.convert("RGBA").save(output,format="PNG")
                    ai_png=output.getvalue()
        except (OSError,ValueError) as exc:
            raise HTTPException(502,"The image provider returned an unreadable poster.") from exc
        if activate:
            c.execute("UPDATE posters SET is_active=0 WHERE event_id=?", (event_id,))
        theme_label = prompt[:42].strip() if prompt else ("Reference Match" if ref_bytes else "AI Studio")
        pid = db.insert(
            c,
            "posters",
            event_id=event_id,
            title=f"{event['name']} · {theme_label}",
            kind="generated",
            prompt=prompt,
            theme=ai_mode,
            design_json="{}",
            svg_content="",
            image_data=ai_png,
            mime_type="image/png",
            is_active=1 if activate else 0,
            created_by="Canvas",
            created_at=now(),
        )
        mode = ai_mode
        theme_name = ai_mode
    else:
        design, mode = _build_design(c, event, prompt, base_design, ref_bytes, ref_mime)
        bg_b64, bg_mime = (None, "image/jpeg")
        if use_ai_image:
            bg_b64, bg_mime = _fetch_pollinations_background(event, design, prompt)
            if bg_b64:
                mode = "Canvas AI Artwork + Vector"
                # Ensure dark scrim contrast on text when using photo/AI artwork background
                design.text_color = "#FFFFFF"
                design.muted_color = "#CBD5E1"
                design.surface_color = "#0B1220"
        svg = render_poster_svg(design, event, sponsors, reg_url, bg_image_b64=bg_b64, bg_image_mime=bg_mime)
        if activate:
            c.execute("UPDATE posters SET is_active=0 WHERE event_id=?", (event_id,))
        pid = db.insert(
            c,
            "posters",
            event_id=event_id,
            title=f"{design.headline} · {prompt[:26].strip() if (bg_b64 and prompt) else design.theme_name}",
            kind="generated",
            prompt=prompt,
            theme=mode if bg_b64 else design.theme_name,
            design_json=design.model_dump_json(),
            svg_content=svg,
            image_data=svg.encode("utf-8"),
            mime_type="image/svg+xml",
            is_active=1 if activate else 0,
            created_by="Canvas",
            created_at=now(),
        )
        theme_name = mode if bg_b64 else design.theme_name

    wid = db.insert(
        c,
        "workflows",
        event_id=event_id,
        trigger="poster_generated",
        request_id=f"poster:{pid}",
        input_hash=pid,
        result="{}",
        created_at=now(),
    )
    summary = (
        f"Canvas generated poster ({theme_name}) for \"{prompt[:70]}\"."
        if prompt
        else f"Canvas designed the {theme_name} poster for {event['name']}."
    )
    db.insert(
        c,
        "runs",
        event_id=event_id,
        workflow_id=wid,
        agent="Canvas",
        trigger="poster_generated",
        tool="revise_poster" if prompt else "generate_poster",
        summary=summary,
        mode=mode,
        status="Completed",
        created_at=now(),
    )
    db.insert(
        c,
        "activity",
        event_id=event_id,
        title="Poster updated by Canvas" if prompt else "Event poster created",
        description=summary,
        agent="Canvas",
        created_at=now(),
    )

    out = _serialize_poster(c.execute("SELECT * FROM posters WHERE id=?", (pid,)).fetchone())
    if ai_err and not ai_png and not (locals().get("bg_b64")):
        out["ai_notice"] = ai_err
    elif ai_err and not ai_png:
        out["ai_info"] = ai_err
    return out


def _serialize_poster(row) -> dict:
    d = dict(row)
    d.pop("image_data", None)
    d.pop("svg_content", None)
    try:
        d["design"] = json.loads(d.pop("design_json") or "{}")
    except Exception:
        d["design"] = {}
    d["is_active"] = bool(d["is_active"])
    d["image_url"] = f"/api/events/{d['event_id']}/posters/{d['id']}/image"
    return d


def list_posters(c, event_id: str) -> list[dict]:
    rows = c.execute(
        "SELECT id, event_id, title, kind, prompt, theme, design_json, mime_type, is_active, created_by, created_at FROM posters WHERE event_id=? ORDER BY rowid DESC",
        (event_id,),
    ).fetchall()
    return [_serialize_poster(r) for r in rows]


router = APIRouter(prefix="/api", tags=["posters"])


class PosterGenerateRequest(BaseModel):
    prompt: str = Field(default="", max_length=1200)
    reference_poster_id: str | None = None
    base_poster_id: str | None = None
    require_ai: bool = False


@router.get("/events/{event_id}/posters")
def get_posters(event_id: str, club: auth.Workspace):
    with db.transaction() as c:
        auth.authorize_event(c, event_id, club["id"])
        posters = list_posters(c, event_id)
    return {"posters": posters}


@router.get("/events/{event_id}/posters/{poster_id}/image")
def get_poster_image(event_id: str, poster_id: str, club: auth.Workspace):
    with db.transaction() as c:
        auth.authorize_event(c, event_id, club["id"])
        row = c.execute(
            "SELECT image_data, svg_content, mime_type FROM posters WHERE id=? AND event_id=?",
            (poster_id, event_id),
        ).fetchone()
    if not row:
        raise HTTPException(404, "Poster not found.")
    data = bytes(row["image_data"]) if row["image_data"] else (row["svg_content"] or "").encode("utf-8")
    return Response(data, media_type=row["mime_type"] or "image/svg+xml")


@router.post("/events/{event_id}/posters/generate")
def generate_poster_route(event_id: str, data: PosterGenerateRequest, club: auth.Workspace):
    with db.transaction(write=True) as c:
        auth.authorize_event(c, event_id, club["id"])
        poster = create_poster_record(
            c,
            event_id=event_id,
            prompt=data.prompt.strip(),
            reference_poster_id=data.reference_poster_id,
            base_poster_id=data.base_poster_id,
            require_ai=data.require_ai,
            activate=True,
        )
        posters = list_posters(c, event_id)
    return {"message": f"Poster generated ({poster['theme']}).", "poster": poster, "posters": posters}


@router.post("/events/{event_id}/posters/upload")
def upload_poster_route(
    event_id: str,
    club: auth.Workspace,
    mode: str = Form("reference"),
    prompt: str = Form(""),
    file: UploadFile = File(...),
    generate: bool = Form(True),
):
    if mode not in ("reference", "final"):
        raise HTTPException(422, "Upload mode must be 'reference' or 'final'.")

    allowed_mimes = {
        "image/png": "image/png",
        "image/jpeg": "image/jpeg",
        "image/jpg": "image/jpeg",
        "image/webp": "image/webp",
        "image/svg+xml": "image/svg+xml",
    }
    mime = (file.content_type or "").lower()
    if mime not in allowed_mimes:
        name = (file.filename or "").lower()
        if name.endswith(".png"):
            mime = "image/png"
        elif name.endswith((".jpg", ".jpeg")):
            mime = "image/jpeg"
        elif name.endswith(".webp"):
            mime = "image/webp"
        elif name.endswith(".svg"):
            mime = "image/svg+xml"
        else:
            raise HTTPException(415, "Upload a PNG, JPG, WEBP, or SVG poster image.")

    raw = file.file.read(4_500_001)
    if not raw or len(raw) > 4_500_000:
        raise HTTPException(413, "Poster file must be smaller than 4.5 MB.")

    with db.transaction(write=True) as c:
        auth.authorize_event(c, event_id, club["id"])
        event = get_event(c, event_id)

        if mode == "final":
            c.execute("UPDATE posters SET is_active=0 WHERE event_id=?", (event_id,))

        pid = db.insert(
            c,
            "posters",
            event_id=event_id,
            title=f"{file.filename or 'Uploaded Poster'} ({'Final' if mode == 'final' else 'Reference'})",
            kind=mode,
            prompt=prompt.strip(),
            theme="User Upload",
            design_json="{}",
            svg_content="",
            image_data=raw,
            mime_type=allowed_mimes[mime],
            is_active=1 if mode == "final" else 0,
            created_by="Organizer",
            created_at=now(),
        )

        db.insert(
            c,
            "activity",
            event_id=event_id,
            title=f"Uploaded {mode} poster",
            description=f"Organizer uploaded {file.filename or 'poster'} as {mode} poster for {event['name']}.",
            agent="Canvas",
            created_at=now(),
        )

        generated = None
        if mode == "reference" and generate:
            generated = create_poster_record(
                c,
                event_id=event_id,
                prompt=prompt.strip() or "Match the color palette and style of the uploaded reference poster.",
                reference_poster_id=pid,
                activate=True,
            )

        posters = list_posters(c, event_id)

    return {
        "message": "Final poster uploaded and set active." if mode == "final" else "Reference poster attached." if not generated else "Reference attached and a template preview created.",
        "uploaded_id": pid,
        "generated": generated,
        "posters": posters,
    }


@router.post("/events/{event_id}/posters/{poster_id}/activate")
def activate_poster_route(event_id: str, poster_id: str, club: auth.Workspace):
    with db.transaction(write=True) as c:
        auth.authorize_event(c, event_id, club["id"])
        row = c.execute(
            "SELECT id FROM posters WHERE id=? AND event_id=?", (poster_id, event_id)
        ).fetchone()
        if not row:
            raise HTTPException(404, "Poster not found.")
        c.execute("UPDATE posters SET is_active=0 WHERE event_id=?", (event_id,))
        c.execute("UPDATE posters SET is_active=1 WHERE id=?", (poster_id,))
        posters = list_posters(c, event_id)
    return {"message": "Active event poster updated.", "posters": posters}


@router.delete("/events/{event_id}/posters/{poster_id}")
def delete_poster_route(event_id: str, poster_id: str, club: auth.Workspace):
    with db.transaction(write=True) as c:
        auth.authorize_event(c, event_id, club["id"])
        row = c.execute(
            "SELECT is_active FROM posters WHERE id=? AND event_id=?", (poster_id, event_id)
        ).fetchone()
        if not row:
            raise HTTPException(404, "Poster not found.")
        c.execute("DELETE FROM posters WHERE id=?", (poster_id,))
        if row["is_active"]:
            nxt = c.execute(
                "SELECT id FROM posters WHERE event_id=? AND kind!='reference' ORDER BY rowid DESC LIMIT 1",
                (event_id,),
            ).fetchone()
            if nxt:
                c.execute("UPDATE posters SET is_active=1 WHERE id=?", (nxt["id"],))
        posters = list_posters(c, event_id)
    return {"message": "Poster removed.", "posters": posters}
