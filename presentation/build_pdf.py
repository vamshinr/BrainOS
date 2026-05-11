"""Build a fully self-contained PDF deck for BrainOS — all images embedded, no external deps.

Output: BrainOS_Hackathon_Deck.pdf (16:9, 13.33x7.5 in / 960x540 pt).
"""
import os
from pathlib import Path

from PIL import Image
from reportlab.lib.colors import HexColor
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, Frame

HERE = Path(__file__).resolve().parent
OUT = HERE / "BrainOS_Hackathon_Deck.pdf"

PAGE_W, PAGE_H = 960, 540  # 13.33 x 7.5 inch widescreen

C = {
    "bg":      HexColor("#0b0d12"),
    "card":    HexColor("#13151c"),
    "card2":   HexColor("#181b24"),
    "border":  HexColor("#2a2e3a"),
    "accent":  HexColor("#f97316"),
    "accent2": HexColor("#fb923c"),
    "accent_soft": HexColor("#3a1d0b"),
    "dim":     HexColor("#94a3b8"),
    "muted":   HexColor("#64748b"),
    "good":    HexColor("#22c55e"),
    "bad":     HexColor("#ef4444"),
    "blue":    HexColor("#3b82f6"),
    "purple":  HexColor("#a855f7"),
    "cyan":    HexColor("#22d3ee"),
    "amd":     HexColor("#ed1c24"),
    "text":    HexColor("#d8dee9"),
    "white":   HexColor("#ffffff"),
    "code_bg": HexColor("#3a1d0b"),
    "code_fg": HexColor("#fed7aa"),
}

FONT       = "Helvetica"
FONT_BOLD  = "Helvetica-Bold"
FONT_OBL   = "Helvetica-Oblique"
FONT_MONO  = "Courier"
FONT_MONOB = "Courier-Bold"


# ── helpers ──────────────────────────────────────────────────────────────────
def fill(c, color):
    c.setFillColor(color)


def stroke(c, color, w=0.5):
    c.setStrokeColor(color)
    c.setLineWidth(w)


def bg(c):
    fill(c, C["bg"])
    c.rect(0, 0, PAGE_W, PAGE_H, stroke=0, fill=1)


def topline(c, section):
    fill(c, C["accent"])
    c.setFont(FONT_BOLD, 8)
    c.drawString(40, PAGE_H - 22, "BRAINOS")
    fill(c, C["dim"])
    c.setFont(FONT, 8)
    c.drawRightString(PAGE_W - 40, PAGE_H - 22, section.upper())
    stroke(c, C["border"], 0.5)
    c.line(40, PAGE_H - 30, PAGE_W - 40, PAGE_H - 30)


def footline(c, page_n, total):
    fill(c, C["muted"])
    c.setFont(FONT, 7)
    c.drawString(40, 18, f"BrainOS · AMD Hackathon 2026")
    c.drawRightString(PAGE_W - 40, 18, f"{page_n} / {total}")


def h4(c, x, y, text, color=None):
    fill(c, color or C["dim"])
    c.setFont(FONT_BOLD, 9)
    c.drawString(x, y, text.upper())


def h2(c, x, y, text, accent_words=None, size=30):
    """Title that supports inline accent coloring of certain word-runs."""
    c.setFont(FONT_BOLD, size)
    if accent_words is None:
        fill(c, C["white"])
        c.drawString(x, y, text)
        return
    # Split on first occurrence of each accent word
    cursor_x = x
    remaining = text
    for word in accent_words:
        if word in remaining:
            before, _, after = remaining.partition(word)
            fill(c, C["white"])
            c.drawString(cursor_x, y, before)
            cursor_x += c.stringWidth(before, FONT_BOLD, size)
            fill(c, C["accent"])
            c.drawString(cursor_x, y, word)
            cursor_x += c.stringWidth(word, FONT_BOLD, size)
            remaining = after
    fill(c, C["white"])
    c.drawString(cursor_x, y, remaining)


def small_text(c, x, y, text, color=None, size=9, font=FONT):
    fill(c, color or C["text"])
    c.setFont(font, size)
    c.drawString(x, y, text)


def rounded_card(c, x, y, w, h, fill_color=None, border_color=None, radius=6, fill_alpha=1.0):
    fill_color = fill_color or C["card"]
    border_color = border_color or C["border"]
    stroke(c, border_color, 0.7)
    fill(c, fill_color)
    c.roundRect(x, y, w, h, radius, stroke=1, fill=1)


def tag(c, x, y, text, bg_color=None, fg_color=None):
    """Returns x advance after drawing the tag."""
    bg_color = bg_color or C["accent"]
    fg_color = fg_color or HexColor("#000000")
    c.setFont(FONT_BOLD, 7)
    tw = c.stringWidth(text.upper(), FONT_BOLD, 7)
    pad_x, pad_y = 6, 3
    fill(c, bg_color)
    c.roundRect(x, y - 2, tw + pad_x * 2, 12, 2, stroke=0, fill=1)
    fill(c, fg_color)
    c.drawString(x + pad_x, y, text.upper())
    return x + tw + pad_x * 2 + 4


def para(c, x, y, w, h, html, base_size=9, align="left", text_color=None, leading=12):
    """Render rich text via Paragraph."""
    text_color = text_color or C["text"]
    style = ParagraphStyle(
        "p",
        fontName=FONT,
        fontSize=base_size,
        leading=leading,
        textColor=text_color,
        alignment={"left": 0, "center": 1, "right": 2}[align],
    )
    p = Paragraph(html, style)
    f = Frame(x, y, w, h, leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0, showBoundary=0)
    f.addFromList([p], c)


def bullet_list(c, x, y, w, h, items, base_size=8.5, color=None, marker="•", marker_color=None, leading=12):
    color = color or C["text"]
    marker_color = marker_color or C["accent"]
    body = ""
    for it in items:
        body += f'<font color="#{_hex(marker_color)}">{marker}</font>&nbsp;&nbsp;{it}<br/>'
    para(c, x, y, w, h, body, base_size=base_size, text_color=color, leading=leading)


def check_list(c, x, y, w, h, items, color=None, base_size=8, leading=11):
    color = color or C["text"]
    return bullet_list(c, x, y, w, h, items, base_size=base_size, color=color,
                       marker="✓", marker_color=C["good"], leading=leading)


def x_list(c, x, y, w, h, items, color=None, base_size=8, leading=11):
    color = color or C["text"]
    return bullet_list(c, x, y, w, h, items, base_size=base_size, color=color,
                       marker="✗", marker_color=C["bad"], leading=leading)


def _hex(col):
    return col.hexval()[2:] if hasattr(col, "hexval") else str(col)[1:]


def fit_image(c, path, x, y, max_w, max_h, border=True):
    """Draw image inside max box preserving aspect ratio, centered."""
    p = HERE / path
    if not p.exists():
        # macOS screenshots use U+202F NARROW NO-BREAK SPACE before AM/PM
        alt = HERE / path.replace(" AM", " AM").replace(" PM", " PM")
        if alt.exists():
            p = alt
    if not p.exists():
        rounded_card(c, x, y, max_w, max_h, fill_color=C["card"], border_color=C["border"])
        small_text(c, x + 8, y + max_h - 14, f"missing: {path}", color=C["bad"], size=7)
        return
    with Image.open(p) as im:
        iw, ih = im.size
    ratio = min(max_w / iw, max_h / ih)
    dw, dh = iw * ratio, ih * ratio
    dx = x + (max_w - dw) / 2
    dy = y + (max_h - dh) / 2
    if border:
        stroke(c, C["border"], 0.7)
        fill(c, HexColor("#000000"))
        c.roundRect(x, y, max_w, max_h, 6, stroke=1, fill=1)
    c.drawImage(str(p), dx, dy, width=dw, height=dh, preserveAspectRatio=True, anchor="c", mask="auto")


def code_chip(c, text, x, y, size=8):
    c.setFont(FONT_MONO, size)
    tw = c.stringWidth(text, FONT_MONO, size)
    pad = 4
    fill(c, C["code_bg"])
    c.roundRect(x - pad, y - 2, tw + pad * 2, size + 4, 2, stroke=0, fill=1)
    fill(c, C["code_fg"])
    c.drawString(x, y, text)
    return x + tw + pad * 2 + 2


# ── slides ───────────────────────────────────────────────────────────────────
def slide_cover(c):
    bg(c)
    # Soft accent glow at top
    for i, alpha in enumerate([0.12, 0.08, 0.04]):
        fill(c, C["accent"])
        c.setFillAlpha(alpha)
        c.circle(PAGE_W / 2, PAGE_H + 40 - i * 30, 220 - i * 40, stroke=0, fill=1)
    c.setFillAlpha(1.0)

    # Badge
    badge_text = "AMD HACKATHON · 2026"
    c.setFont(FONT_BOLD, 8)
    bw = c.stringWidth(badge_text, FONT_BOLD, 8)
    bx = PAGE_W / 2 - (bw + 24) / 2
    by = 410
    fill(c, C["amd"])
    c.roundRect(bx, by, bw + 24, 18, 9, stroke=0, fill=1)
    fill(c, C["white"])
    c.drawCentredString(PAGE_W / 2, by + 5, badge_text)

    # BrainOS title
    title = "BrainOS"
    c.setFont(FONT_BOLD, 88)
    fill(c, C["white"])
    c.drawCentredString(PAGE_W / 2, 320, title)
    # Accent stripe under title
    fill(c, C["accent"])
    c.rect(PAGE_W / 2 - 50, 305, 100, 4, stroke=0, fill=1)

    fill(c, C["text"])
    c.setFont(FONT, 18)
    c.drawCentredString(PAGE_W / 2, 270, "The layer between scattered company knowledge and AI agents.")

    fill(c, C["dim"])
    c.setFont(FONT, 12)
    c.drawCentredString(PAGE_W / 2, 244, "Multi-agent  ·  Multi-modal  ·  Knowledge graph  ·  AMD MI300X")

    # Tag pills
    pills = [
        ("directed graph", C["accent"], HexColor("#000000")),
        ("supersession",   C["blue"],   C["white"]),
        ("gap detection",  C["good"],   HexColor("#000000")),
        ("multimodal VLM", C["purple"], C["white"]),
        ("Slack-native",   C["cyan"],   HexColor("#000000")),
        ("self-hostable",  HexColor("#1f2330"), C["text"]),
    ]
    # Pre-compute total width
    c.setFont(FONT_BOLD, 8)
    widths = [c.stringWidth(t.upper(), FONT_BOLD, 8) + 18 for t, _, _ in pills]
    gap = 8
    total = sum(widths) + gap * (len(pills) - 1)
    px = (PAGE_W - total) / 2
    py = 200
    for (text, bgc, fgc), w in zip(pills, widths):
        fill(c, bgc)
        c.roundRect(px, py, w, 16, 8, stroke=0, fill=1)
        fill(c, fgc)
        c.setFont(FONT_BOLD, 8)
        c.drawCentredString(px + w / 2, py + 5, text.upper())
        px += w + gap

    # Team / links
    fill(c, C["dim"])
    c.setFont(FONT, 10)
    c.drawCentredString(PAGE_W / 2, 150, "Noel  ·  Rajveer  ·  Vamshi")
    c.setFont(FONT, 9)
    c.drawCentredString(PAGE_W / 2, 132, "github.com/vamshinr/BrainOS    •    Live: 129.212.176.117:3000")


def slide_problem(c):
    bg(c); topline(c, "Problem")
    h4(c, 40, 480, "The problem")
    h2(c, 40, 442, "Every company has a hidden second corpus.", accent_words=["second corpus."], size=26)

    # Quote
    quote = '"I think every company in the world is going to need one." — Tom Blomfield, Y Combinator · RFS: Company Brain'
    fill(c, C["accent"])
    c.rect(40, 380, 3, 36, stroke=0, fill=1)
    fill(c, C["text"])
    c.setFont(FONT_OBL, 10)
    c.drawString(54, 400, quote)

    # Two cards
    cw, ch = 420, 210
    pad = 20
    x1, y1 = 40, 105
    x2, y2 = 40 + cw + pad, 105

    rounded_card(c, x1, y1, cw, ch, fill_color=HexColor("#0c1727"), border_color=C["blue"])
    fill(c, C["blue"])
    c.setFont(FONT_BOLD, 12)
    c.drawString(x1 + 18, y1 + ch - 24, "Where knowledge actually lives")
    bullet_list(c, x1 + 18, y1 + 16, cw - 36, ch - 56, [
        "Slack threads that scroll into history",
        "PDFs updated by email, not the doc",
        "Whiteboard photos in personal drives",
        "Architecture diagrams 6 months stale",
        "Three engineers who remember the decision",
        "Contracts that contradict the runbook",
    ], base_size=10, leading=15, marker_color=C["blue"])

    rounded_card(c, x2, y2, cw, ch, fill_color=HexColor("#1d0a0a"), border_color=C["bad"])
    fill(c, C["bad"])
    c.setFont(FONT_BOLD, 12)
    c.drawString(x2 + 18, y2 + ch - 24, "What happens to AI agents today")
    x_list(c, x2 + 18, y2 + 16, cw - 36, ch - 56, [
        "No context → takes the wrong action",
        "Stale policy → legal / compliance liability",
        "Missing owner → ticket stuck for days",
        "Conflicting docs → LLM hallucinates a merge",
        "Can't read diagrams → blind to system design",
        "No output format → agent can't load it",
    ], base_size=10, leading=15)

    fill(c, C["dim"])
    c.setFont(FONT_OBL, 10)
    c.drawCentredString(PAGE_W / 2, 75, "The models crossed the quality bar in 2024. The knowledge layer is what's still missing.")


def slide_solution(c):
    bg(c); topline(c, "Solution")
    h4(c, 40, 480, "The solution")
    h2(c, 40, 442, "BrainOS is the missing knowledge layer.", accent_words=["missing knowledge layer."], size=26)

    cw = (PAGE_W - 80 - 30) / 3
    ch = 160
    y = 200
    cards = [
        ("Ingest anything", C["accent"], HexColor("#2a1408"),
         "Text, PDF, DOCX, images, architecture diagrams, Slack threads, slash commands. One unified pipeline regardless of format."),
        ("Reconcile, don't stack", C["blue"], HexColor("#0c1727"),
         "Every new fact is compared against the existing graph. Old facts are <b>superseded</b>. Contradictions flagged <b>Disputed</b> — not silently buried."),
        ("Agent-ready output", C["good"], HexColor("#0c1f15"),
         "Exports a SKILLS.md per department. Drop into Claude Code, Cursor, OpenAI GPTs, or Aider — the agent operates with full company context."),
    ]
    x = 40
    for title, border_c, bg_c, body in cards:
        rounded_card(c, x, y, cw, ch, fill_color=bg_c, border_color=border_c)
        fill(c, border_c)
        c.setFont(FONT_BOLD, 13)
        c.drawString(x + 18, y + ch - 26, title)
        para(c, x + 18, y + 14, cw - 36, ch - 52, body, base_size=10, leading=14)
        x += cw + 15

    # Pipeline
    pipe_y = 110
    fill(c, C["dim"])
    c.setFont(FONT_BOLD, 9)
    c.drawString(40, pipe_y + 28, "PIPELINE")
    steps = [
        ("Slack/PDF/DOCX/Image", False),
        ("Ingestion Agent", True),
        ("Structuring Agent", True),
        ("Knowledge Graph", False),
        ("SKILLS.md", False),
        ("AI Agent", False),
    ]
    c.setFont(FONT_BOLD, 9)
    widths = [c.stringWidth(t, FONT_BOLD, 9) + 16 for t, _ in steps]
    arrow_w = 14
    total = sum(widths) + arrow_w * (len(steps) - 1)
    px = (PAGE_W - total) / 2
    for i, (text, accent) in enumerate(steps):
        w = widths[i]
        if accent:
            fill(c, C["accent_soft"])
            stroke(c, C["accent"], 0.7)
            c.roundRect(px, pipe_y, w, 22, 4, stroke=1, fill=1)
            fill(c, C["accent"])
        else:
            fill(c, HexColor("#1f2330"))
            stroke(c, C["border"], 0.5)
            c.roundRect(px, pipe_y, w, 22, 4, stroke=1, fill=1)
            fill(c, C["text"])
        c.setFont(FONT_BOLD, 9)
        c.drawCentredString(px + w / 2, pipe_y + 7, text)
        px += w
        if i < len(steps) - 1:
            fill(c, C["accent"])
            c.setFont(FONT_BOLD, 12)
            c.drawCentredString(px + arrow_w / 2, pipe_y + 7, "→")
            px += arrow_w

    fill(c, C["dim"])
    c.setFont(FONT_OBL, 8)
    c.drawCentredString(PAGE_W / 2, pipe_y - 18, "Every step runs on AMD MI300X via vLLM — Qwen 32B + Qwen2-VL 7B co-resident on a single card.")


def slide_why_matters(c):
    bg(c); topline(c, "Why it matters")
    h4(c, 40, 480, "Why this actually matters")
    h2(c, 40, 442, "Five things every company gets, on day one.",
       accent_words=["on day one."], size=24)

    points = [
        ("①", C["accent"], "Conflict surfacing prevents the \"we decided what?\" problem.",
         "When two docs disagree, both get kept with a Disputed badge. The argument surfaces instead of being silently averaged by an LLM."),
        ("②", C["blue"], "Knowledge gap analysis becomes a hiring / focus tool.",
         "missing_owner, undescribed_entity, open_dispute — a deterministic punch list of what the org is blind to. Drives priorities, not vibes."),
        ("③", C["good"], "You don't need to write docs you'd never write anyway.",
         "Slack threads, whiteboard photos, PDFs already exist. BrainOS reconciles them into structured facts — no parallel doc culture required."),
        ("④", C["purple"], "Your AI agents become useful on day one.",
         "SKILLS.md drops into Claude Code, Cursor, GPTs, Aider. Agents inherit full company context — ownership, policies, gotchas, conflicts."),
        ("⑤", C["cyan"], "You don't lose context when someone leaves.",
         "Maya's departure becomes an event the graph processes, not a fire drill. Ownership edges rewire; orphaned tasks surface as gaps."),
    ]
    card_h = 62
    gap = 8
    y = 410 - card_h
    for num, color, headline, body in points:
        rounded_card(c, 40, y, PAGE_W - 80, card_h, fill_color=C["card"], border_color=color)
        # number badge
        fill(c, color)
        c.circle(70, y + card_h / 2, 14, stroke=0, fill=1)
        fill(c, C["bg"])
        c.setFont(FONT_BOLD, 14)
        c.drawCentredString(70, y + card_h / 2 - 5, num)
        # headline
        fill(c, C["white"])
        c.setFont(FONT_BOLD, 12)
        c.drawString(98, y + card_h - 22, headline)
        # body
        fill(c, C["dim"])
        c.setFont(FONT, 9)
        c.drawString(98, y + 14, body)
        y -= card_h + gap


def slide_features_examples(c):
    bg(c); topline(c, "Features in action")
    h4(c, 40, 480, "Features in action")
    h2(c, 40, 442, "Four capabilities. One real query each.",
       accent_words=["One real query each."], size=22)

    fill(c, C["dim"])
    c.setFont(FONT, 9)
    c.drawString(40, 412, "All from the Helix Outdoor demo brain — same graph, four different retrieval modes.")

    cw = (PAGE_W - 80 - 20) / 2
    ch = 175
    positions = [
        (40, 220),
        (60 + cw, 220),
        (40, 30),
        (60 + cw, 30),
    ]

    features = [
        ("Answer from graph", C["accent"], HexColor("#2a1408"),
         "Q: Who owns the Saigon TexCo factory relationship right now?",
         "A: Marco Ferraro (acting). The fact lives in an <i>edge</i> (Marco → Saigon TexCo), not a doc. No vector embedding would ever retrieve this."),
        ("Temporal + supersession", C["blue"], HexColor("#0c1727"),
         "Q: CX Lead refund limit today? · And in April 2026?",
         "A today: <b>$1,000</b> (eff 2026-05-01). A April: <b>$2,000</b>. Old policy marked [SUPERSEDED], not deleted — both answers correct, neither hallucinated."),
        ("Multimodal (VLM)", C["purple"], HexColor("#1a0d23"),
         "Q: Looking at the architecture diagram, what's the most fragile webhook?",
         "A: The <b>ShipBob webhook</b> — VLM reads the diagram, fuses with a Slack thread about a missing HMAC signature check on retries."),
        ("Knowledge gap analysis", C["cyan"], HexColor("#0c1d23"),
         "Q: What doesn't Helix Outdoor know about itself?",
         "A: 5 gaps — 2 missing_owner, 1 undescribed_entity, 1 orphan_gotcha, 1 open_dispute. Deterministic graph scan — no LLM call."),
    ]
    for (title, border_c, bg_c, q, a), (x, y) in zip(features, positions):
        rounded_card(c, x, y, cw, ch, fill_color=bg_c, border_color=border_c)
        fill(c, border_c)
        c.setFont(FONT_BOLD, 12)
        c.drawString(x + 16, y + ch - 24, title)
        # Q line
        fill(c, C["dim"])
        c.setFont(FONT_BOLD, 8)
        c.drawString(x + 16, y + ch - 46, "QUERY")
        para(c, x + 16, y + ch - 88, cw - 32, 36, q, base_size=9.5, leading=12.5, text_color=C["white"])
        # A block
        fill(c, C["dim"])
        c.setFont(FONT_BOLD, 8)
        c.drawString(x + 16, y + ch - 102, "BRAINOS ANSWER")
        para(c, x + 16, y + 10, cw - 32, ch - 130, a, base_size=9, leading=12, text_color=C["text"])


def slide_dashboard_hero(c):
    bg(c); topline(c, "Built & live")
    h4(c, 40, 480, "What it looks like")
    h2(c, 40, 442, "Not a slide deck. A live product.", accent_words=["A live product."], size=26)
    fit_image(c, "Screenshot 2026-05-10 at 11.01.23 AM.png", 60, 70, PAGE_W - 120, 350)
    fill(c, C["dim"])
    c.setFont(FONT, 8)
    c.drawCentredString(PAGE_W / 2, 50,
                        "Dashboard at 129.212.176.117:3000  ·  101 entities  ·  62 relationships  ·  62 knowledge units  ·  0 superseded after reconcile")


def slide_not_rag(c):
    bg(c); topline(c, "Differentiation")
    h4(c, 40, 480, "Differentiation")
    h2(c, 40, 442, "This is not RAG.", accent_words=["not"], size=28)

    cw = (PAGE_W - 80 - 20) / 2
    ch = 230
    y = 110

    rounded_card(c, 40, y, cw, ch, fill_color=HexColor("#1d0a0a"), border_color=C["bad"])
    fill(c, C["bad"])
    c.setFont(FONT_BOLD, 14)
    c.drawString(58, y + ch - 28, "Vanilla RAG")
    x_list(c, 58, y + 18, cw - 36, ch - 54, [
        "Embed → cosine → top-k chunks → LLM",
        "One retrieval signal (vector only)",
        "Keeps old + new policy <b>simultaneously</b>",
        "No graph — can't traverse ownership",
        "Blind to images, diagrams, whiteboards",
        "Hallucinates when sources conflict",
        "Says \"yes\" when it has no data",
    ], base_size=10.5, leading=17)

    x2 = 60 + cw
    rounded_card(c, x2, y, cw, ch, fill_color=HexColor("#0c1f15"), border_color=C["good"])
    fill(c, C["good"])
    c.setFont(FONT_BOLD, 14)
    c.drawString(x2 + 18, y + ch - 28, "BrainOS")
    check_list(c, x2 + 18, y + 18, cw - 36, ch - 54, [
        "5-signal hybrid retrieval + RRF rerank",
        "Vector + BM25 + entity + graph + multimodal",
        "Temporal scoring — <b>one fact wins</b> per query",
        "Graph walk: Customer → CSM → escalation chain",
        "VLM reads diagrams, whiteboards, org charts",
        "Disputed badge — both kept, conflict exposed",
        "Gap analysis — <b>knows what it doesn't know</b>",
    ], base_size=10.5, leading=17)


def slide_four_agents(c):
    bg(c); topline(c, "Architecture")
    h4(c, 40, 480, "Architecture")
    h2(c, 40, 442, "Four specialized agents — not one mega-prompt.",
       accent_words=["not one mega-prompt."], size=24)

    cw = (PAGE_W - 80 - 30) / 4
    ch = 200
    y = 160
    agents = [
        ("①  Ingestion", C["accent"], HexColor("#2a1408"),
         ["Sentence-aware chunking", "Qwen2-VL 7B for images", "Atomic unit extraction", "Retry with backoff"]),
        ("②  Structuring", C["blue"], HexColor("#0c1727"),
         ["Embed → ChromaDB HNSW", "Reconcile: 4 verdicts", "validTo + supersededAt", "Merges into brain.json"]),
        ("③  Execution", C["purple"], HexColor("#1a0d23"),
         ["5-signal hybrid retrieval", "Temporal rerank", "Stale filter", "Inline-cited answer gen"]),
        ("④  Feedback", C["cyan"], HexColor("#0c1d23"),
         ["Groundedness audit", "Conf < 0.72 → rewrite", "Pre/post-revision logged", "Verdicts → /api/metrics"]),
    ]
    x = 40
    for title, border_c, bg_c, items in agents:
        rounded_card(c, x, y, cw, ch, fill_color=bg_c, border_color=border_c)
        fill(c, border_c)
        c.setFont(FONT_BOLD, 13)
        c.drawString(x + 16, y + ch - 26, title)
        bullet_list(c, x + 16, y + 18, cw - 32, ch - 54, items,
                    base_size=10, leading=16, marker_color=border_c)
        x += cw + 10

    fill(c, C["dim"])
    c.setFont(FONT_OBL, 10)
    c.drawCentredString(PAGE_W / 2, 120,
        "Per-task model routing: extraction → Qwen 32B  ·  reconciliation → Qwen 32B  ·  vision → Qwen2-VL 7B  ·  feedback → Qwen 32B")


def slide_retrieval(c):
    bg(c); topline(c, "Retrieval")
    h4(c, 40, 480, "Retrieval")
    h2(c, 40, 442, "5-signal hybrid retrieval · RRF fusion · temporal rerank",
       accent_words=["RRF fusion"], size=22)

    # Big card on left: pipeline
    rounded_card(c, 40, 90, 540, 340, fill_color=C["card"], border_color=C["border"])
    fill(c, C["accent"])
    c.setFont(FONT_BOLD, 12)
    c.drawString(60, 410, "QUERY PIPELINE")
    items = [
        ("①", "Vector search on extracted UNITS"),
        ("②", "Vector search on RAW CHUNKS"),
        ("③", "BM25 on UNITS"),
        ("④", "BM25 on RAW CHUNKS"),
        ("⑤", "Entity index + 1-hop graph walk"),
    ]
    yy = 380
    for num, txt in items:
        fill(c, C["accent"])
        c.setFont(FONT_BOLD, 14)
        c.drawString(60, yy, num)
        fill(c, C["text"])
        c.setFont(FONT, 11)
        c.drawString(82, yy, txt)
        yy -= 26
    yy -= 8
    fill(c, C["dim"])
    c.setFont(FONT_OBL, 9)
    c.drawString(60, yy, "↓  all 5 ranked lists")
    yy -= 16
    fill(c, C["accent"])
    c.setFont(FONT_BOLD, 11)
    c.drawString(60, yy, "Reciprocal Rank Fusion (RRF)")
    yy -= 16
    fill(c, C["text"])
    c.setFont(FONT, 10)
    c.drawString(60, yy, "Temporal + confidence rerank  →  stale filter  →  top-k context  →  LLM")

    # Right column: 3 small cards
    rx = 600; rw = PAGE_W - 40 - rx
    why_cards = [
        ("WHY TWO LEVELS?", "Units are LLM-extracted — precise but lossy. Raw chunks are noisy but complete. Each catches what the other misses."),
        ("WHY BM25?", "Vectors miss exact strings: product codes, lot numbers, policy IDs. BM25 catches those."),
        ("WHY GRAPH?", '"Who owns Saigon TexCo?" lives in an <i>edge</i>, not a document. No embedding ever retrieves that.'),
    ]
    cy = 320
    for title, body in why_cards:
        rounded_card(c, rx, cy, rw, 100, fill_color=C["card2"], border_color=C["border"])
        fill(c, C["accent"])
        c.setFont(FONT_BOLD, 9)
        c.drawString(rx + 14, cy + 80, title)
        para(c, rx + 14, cy + 12, rw - 28, 64, body, base_size=9, leading=12)
        cy -= 110


def slide_reconciliation(c):
    bg(c); topline(c, "Reconciliation")
    h4(c, 40, 480, "Reconciliation is the core primitive")
    h2(c, 40, 442, "Old facts get superseded, not stacked.",
       accent_words=["superseded,"], size=26)

    fill(c, C["dim"])
    c.setFont(FONT, 9)
    c.drawString(40, 410, "New unit extracted  →  find existing units with overlapping entities  →  Structuring Agent emits a verdict.")

    # 4 verdict cards
    cw = (PAGE_W - 80 - 30) / 4
    ch = 130
    y = 240
    verdicts = [
        ("supersedes",  C["accent"], HexColor("#2a1408"),
         "Old unit → validTo=now, temporalStatus=historical. Disappears from \"current\" answers."),
        ("duplicate",   C["blue"],   HexColor("#0c1727"),
         "New unit dropped. Source is cross-referenced on the existing unit."),
        ("conflicts",   C["bad"],    HexColor("#1d0a0a"),
         "Both kept. conflictsWith back-reference. <b>Disputed</b> badge in UI."),
        ("independent", C["good"],   HexColor("#0c1f15"),
         "Stored as-is. No effect on existing units."),
    ]
    x = 40
    for title, border_c, bg_c, body in verdicts:
        rounded_card(c, x, y, cw, ch, fill_color=bg_c, border_color=border_c)
        fill(c, border_c)
        c.setFont(FONT_BOLD, 13)
        c.drawString(x + 14, y + ch - 24, title)
        para(c, x + 14, y + 10, cw - 28, ch - 50, body, base_size=9, leading=12)
        x += cw + 10

    # Bottom 2 cards
    cw2 = (PAGE_W - 80 - 20) / 2
    ch2 = 130
    y2 = 75
    rounded_card(c, 40, y2, cw2, ch2, fill_color=HexColor("#1a0d23"), border_color=C["purple"])
    fill(c, C["purple"])
    c.setFont(FONT_BOLD, 12)
    c.drawString(58, y2 + ch2 - 24, "Time-travel queries")
    para(c, 58, y2 + 14, cw2 - 36, ch2 - 50,
         '<i>"What was the refund limit in April?"</i> → temporal scorer boosts expired units.<br/>'
         '<i>"What is the refund limit today?"</i> → temporal scorer penalizes historical units.<br/>'
         '<font color="#22c55e"><b>Both answers correct. Neither hallucinates.</b></font>',
         base_size=10, leading=14)

    x2_card = 60 + cw2
    rounded_card(c, x2_card, y2, cw2, ch2, fill_color=HexColor("#0c1d23"), border_color=C["cyan"])
    fill(c, C["cyan"])
    c.setFont(FONT_BOLD, 12)
    c.drawString(x2_card + 18, y2 + ch2 - 24, "Knowledge gap detection")
    para(c, x2_card + 18, y2 + 14, cw2 - 36, ch2 - 50,
         "Pure graph topology scan, no retrieval:<br/>"
         "• <b>missing_owner</b> — entity with no ownership edge<br/>"
         "• <b>undescribed_entity</b> — named but never defined<br/>"
         "• <b>orphan_gotcha</b> — warning with no owning entity<br/>"
         "• <b>open_dispute</b> — unresolved conflictsWith pair",
         base_size=9.5, leading=13)


def slide_ingest(c):
    bg(c); topline(c, "Live · Ingest")
    h4(c, 40, 480, "Live · /ingest")
    h2(c, 40, 442, "One pipeline, three input modes.", accent_words=["three input modes."], size=26)

    iw = (PAGE_W - 80 - 20) / 2
    ih = 320
    y = 80
    fit_image(c, "Screenshot 2026-05-10 at 11.03.24 AM.png", 40, y, iw, ih)
    fit_image(c, "video_frames/frame_45s.jpg",            60 + iw, y, iw, ih)

    fill(c, C["dim"])
    c.setFont(FONT, 8)
    c.drawString(40, 60, "Text / Paste  ·  File Upload  ·  Image / VLM  — same reconciliation path for all three.")
    c.drawRightString(PAGE_W - 40, 60, "Live demo: 02_slack_maya_departure.txt processing on AMD MI300X.")


def slide_map(c):
    bg(c); topline(c, "Live · Map")
    h4(c, 40, 480, "Live · /map")
    h2(c, 40, 442, "The company knowledge graph — explicit, directed, traversable.",
       accent_words=["company knowledge graph"], size=22)

    iw = (PAGE_W - 80 - 20) / 2
    ih = 320
    y = 80
    fit_image(c, "Screenshot 2026-05-10 at 11.03.52 AM.png", 40, y, iw, ih)
    fit_image(c, "video_frames/frame_15s.jpg",              60 + iw, y, iw, ih)

    fill(c, C["dim"])
    c.setFont(FONT, 8)
    c.drawString(40, 60, "Day 0 — first ingested unit. Single ownership edge: Noel → critical automation tasks.")
    c.drawRightString(PAGE_W - 40, 60, "After full demo dataset — 170 entities, 216 co-mentions.")


def slide_ask(c):
    bg(c); topline(c, "Live · Ask")
    h4(c, 40, 480, "Live · /ask")
    h2(c, 40, 442, "Grounded answers · retrieval diagnostics · per-answer audit.",
       accent_words=["retrieval diagnostics"], size=22)

    fit_image(c, "Screenshot 2026-05-10 at 11.04.04 AM.png", 60, 170, PAGE_W - 120, 240)

    cw = (PAGE_W - 80 - 30) / 3
    ch = 90
    y = 60
    cards = [
        ("Grounded", C["accent"], HexColor("#2a1408"),
         "Every answer carries a grounding badge, confidence (0-1), and inline source citations [F1], [R2]."),
        ("Diagnostic", C["blue"], HexColor("#0c1727"),
         "Retrieval debug pane shows all 6 signal types — vector, BM25, entity, graph — per query."),
        ("Honest", C["good"], HexColor("#0c1f15"),
         "\"Brain does not have this\" instead of hallucinating. Draft vs revised answer disclosed when verifier rewrites."),
    ]
    x = 40
    for title, border_c, bg_c, body in cards:
        rounded_card(c, x, y, cw, ch, fill_color=bg_c, border_color=border_c)
        fill(c, border_c)
        c.setFont(FONT_BOLD, 11)
        c.drawString(x + 14, y + ch - 22, title)
        para(c, x + 14, y + 10, cw - 28, ch - 36, body, base_size=8.5, leading=11)
        x += cw + 15


def slide_skills(c):
    bg(c); topline(c, "Live · Skills export")
    h4(c, 40, 480, "Output format")
    h2(c, 40, 442, "SKILLS.md — the portable company brain.",
       accent_words=["the portable company brain."], size=24)

    iw = (PAGE_W - 80 - 20) / 2
    ih = 240
    y = 160
    fit_image(c, "Screenshot 2026-05-10 at 11.04.10 AM.png", 40, y, iw, ih)
    fit_image(c, "video_frames/frame_80s.jpg",              60 + iw, y, iw, ih)

    cw = (PAGE_W - 80 - 20) / 2
    ch = 110
    y2 = 40
    rounded_card(c, 40, y2, cw, ch, fill_color=C["card"], border_color=C["border"])
    fill(c, C["accent"])
    c.setFont(FONT_BOLD, 11)
    c.drawString(58, y2 + ch - 22, "What's in a SKILLS.md")
    para(c, 58, y2 + 12, cw - 36, ch - 46,
         "Scope · Operational Facts · Ownership &amp; Routing · Active Policies · Processes · Gotchas · Decisions · Temporal Notes · <b>Agent Rules</b> (≥0.75 conf) · Graph Relationships · Source Index. Scoped per department — Legal doesn't see Finance.",
         base_size=9, leading=12.5)

    rounded_card(c, 60 + cw, y2, cw, ch, fill_color=HexColor("#2a1408"), border_color=C["accent"])
    fill(c, C["accent"])
    c.setFont(FONT_BOLD, 11)
    c.drawString(78 + cw, y2 + ch - 22, "Sample Agent Rules")
    snippet = (
        "- Webhook: missing X-Shipbob-Signature MUST 400.",
        "- Lot 24-A-118: DO NOT restock; full refund.",
        "- Saigon TexCo → Marco Ferraro (acting).",
        "- CX Lead refund cap = $1,000 (eff 2026-05-01).",
    )
    fill(c, C["code_fg"])
    c.setFont(FONT_MONO, 8)
    sy = y2 + ch - 40
    for line in snippet:
        c.drawString(78 + cw, sy, line)
        sy -= 11


def slide_slack_mcp(c):
    bg(c); topline(c, "Live · Slack MCP")
    h4(c, 40, 480, "Integration")
    h2(c, 40, 442, "The brain lives where the team talks.",
       accent_words=["talks."], size=26)

    iw = (PAGE_W - 80 - 20) / 2
    ih = 250
    y = 150
    fit_image(c, "Screenshot 2026-05-10 at 11.04.18 AM.png", 40, y, iw, ih)
    fit_image(c, "video_frames/frame_115s.jpg",             60 + iw, y, iw, ih)

    cw = (PAGE_W - 80 - 30) / 3
    ch = 100
    y2 = 40
    cards = [
        ("Real-time ingest", C["accent"], HexColor("#2a1408"),
         "Single thread, entire channel, or semantic search result — same reconciliation pipeline as file uploads."),
        ("/brainos slash", C["blue"], HexColor("#0c1727"),
         "Full verifier-revision loop before posting. Answer + confidence label + source list, in-channel."),
        ("Canvas export", C["good"], HexColor("#0c1f15"),
         "Per-department knowledge as a Slack Canvas. Team annotates without leaving Slack."),
    ]
    x = 40
    for title, border_c, bg_c, body in cards:
        rounded_card(c, x, y2, cw, ch, fill_color=bg_c, border_color=border_c)
        fill(c, border_c)
        c.setFont(FONT_BOLD, 11)
        c.drawString(x + 14, y2 + ch - 22, title)
        para(c, x + 14, y2 + 12, cw - 28, ch - 46, body, base_size=9, leading=12)
        x += cw + 15


def slide_slack_action(c):
    bg(c); topline(c, "Slack · in action")
    h4(c, 40, 480, "Slack · in action")
    h2(c, 40, 442, "Grounded answers, in-thread, with sources.",
       accent_words=["in-thread,"], size=24)

    iw = (PAGE_W - 80 - 20) / 2
    ih = 320
    y = 70
    fit_image(c, "video_frames/frame_150s.jpg", 40, y, iw, ih)
    fit_image(c, "video_frames/frame_250s.jpg", 60 + iw, y, iw, ih)

    fill(c, C["dim"])
    c.setFont(FONT, 8)
    c.drawCentredString(PAGE_W / 2, 50,
        "Real questions in #all-brainos: defective-lot SLA, Saigon TexCo ownership, refund limits, architecture webhooks.")
    c.drawCentredString(PAGE_W / 2, 38,
        "Every reply cites F1, F2, source IDs, confidence label.  HMAC signature verification on every request.")


def slide_amd(c):
    bg(c); topline(c, "Infrastructure")
    h4(c, 40, 480, "Why AMD MI300X is the right hardware")
    h2(c, 40, 442, "192 GB HBM3 — co-resident text + vision on one card.",
       accent_words=["one card."], size=22)

    cw = (PAGE_W - 80 - 30) / 3
    ch = 90
    y = 320
    stats = [
        ("192GB", "HBM3 — co-reside Qwen 32B + Qwen2-VL 7B"),
        ("1 GPU", "vs 3× H100 for the same workload"),
        ("<2s",   "end-to-end answer latency on vLLM"),
    ]
    x = 40
    for big, small in stats:
        rounded_card(c, x, y, cw, ch, fill_color=HexColor("#1a0808"), border_color=C["amd"])
        fill(c, C["amd"])
        c.setFont(FONT_BOLD, 32)
        c.drawCentredString(x + cw / 2, y + 38, big)
        fill(c, C["dim"])
        c.setFont(FONT_BOLD, 8)
        c.drawCentredString(x + cw / 2, y + 14, small.upper())
        x += cw + 15

    fit_image(c, "Screenshot 2026-05-10 at 11.04.25 AM.png", 60, 70, PAGE_W - 120, 230)
    fill(c, C["dim"])
    c.setFont(FONT, 8)
    c.drawCentredString(PAGE_W / 2, 50,
        "Live /metrics  ·  Prometheus scrape  ·  gen tok/s  ·  prompt tok/s  ·  KV-cache util  ·  per-call log of every LLM call.")


def slide_demo_scenario(c):
    bg(c); topline(c, "Demo · Helix Outdoor")
    h4(c, 40, 480, "Demo scenario")
    h2(c, 40, 442, "Helix Outdoor — Series-B D2C outdoor brand.",
       accent_words=["Series-B D2C"], size=24)

    fill(c, C["text"])
    c.setFont(FONT, 10)
    c.drawString(40, 408,
        "Ops-heavy company chosen deliberately: factory contracts, 3PL logistics, multi-jurisdiction policy, QC whiteboards, org charts with vacant roles.")
    fill(c, C["accent"])
    c.setFont(FONT_BOLD, 10)
    c.drawString(40, 392, "10 sources  ·  4 file types  ·  7 capability tiers")

    iw = (PAGE_W - 80 - 20) / 2
    ih = 220
    y = 150
    fit_image(c, "video_frames/frame_220s.jpg", 40, y, iw, ih)
    fit_image(c, "video_frames/frame_185s.jpg", 60 + iw, y, iw, ih)

    cw = (PAGE_W - 80 - 20) / 2
    ch = 80
    y2 = 50
    rounded_card(c, 40, y2, cw, ch, fill_color=C["card"], border_color=C["border"])
    para(c, 56, y2 + 6, cw - 32, ch - 12,
         '<b><font color="#f97316">Q5 (temporal):</font></b> "CX Lead refund limit today?" → <b>$1,000</b> with [SUPERSEDED] on old $2,000.<br/>'
         '<b><font color="#f97316">Q6 (time-travel):</font></b> "Limit in April?" → <b>$2,000</b>. Brain prefers historical for past-tense queries.',
         base_size=8.5, leading=12)

    rounded_card(c, 60 + cw, y2, cw, ch, fill_color=C["card"], border_color=C["border"])
    para(c, 76 + cw, y2 + 6, cw - 32, ch - 12,
         '<b><font color="#f97316">Q10 (multimodal):</font></b> "Most fragile webhook?" → VLM reads architecture diagram + fuses with Slack thread.<br/>'
         '<b><font color="#f97316">Q12 (gap):</font></b> "What doesn\'t Helix know?" → deterministic graph scan returns 5+ items.',
         base_size=8.5, leading=12)


def slide_video_frames_grid(c):
    """A 4-up frames grid in lieu of a playable video embed."""
    bg(c); topline(c, "Demo · Walkthrough")
    h4(c, 40, 480, "Demo walkthrough — selected frames")
    h2(c, 40, 442, "4-minute walkthrough — end-to-end.",
       accent_words=["end-to-end."], size=24)

    cells = [
        ("video_frames/frame_15s.jpg",  "0:15  —  Knowledge graph at scale (170 entities)"),
        ("video_frames/frame_45s.jpg",  "0:45  —  File upload — 70B model on AMD MI300X"),
        ("video_frames/frame_80s.jpg",  "1:20  —  SKILLS.md export, Operations dept"),
        ("video_frames/frame_115s.jpg", "1:55  —  @BrainOS answers in Slack with citations"),
    ]
    cw = (PAGE_W - 80 - 20) / 2
    ch = 175
    positions = [
        (40, 230),
        (60 + cw, 230),
        (40, 50),
        (60 + cw, 50),
    ]
    for (path, caption), (x, y) in zip(cells, positions):
        fit_image(c, path, x, y, cw, ch)
        fill(c, C["dim"])
        c.setFont(FONT_BOLD, 7.5)
        c.drawString(x + 4, y - 10, caption)


def slide_shipped(c):
    bg(c); topline(c, "Shipped")
    h4(c, 40, 480, "What's shipped")
    h2(c, 40, 442, "Built — not planned.", accent_words=["not planned."], size=26)

    cw = (PAGE_W - 80 - 30) / 3
    ch = 280
    y = 90
    cols = [
        ("Backend (Python / FastAPI)", C["blue"], HexColor("#0c1727"), [
            "4-agent pipeline",
            "Per-task model routing (env)",
            "Per-request model picker (UI)",
            "5-signal hybrid retrieval + RRF",
            "Reconciliation engine (4 verdicts)",
            "Temporal scoring + time-travel",
            "Stale marking + validTo",
            "Verifier-revision loop",
            "VLM image ingestion pipeline",
            "PDF / DOCX / DOC / TXT / CSV",
        ]),
        ("Frontend (Next.js 15)", C["accent"], HexColor("#2a1408"), [
            "Dashboard — stats + recent",
            "Force-directed graph (zoom/pan)",
            "/ingest — text + file + image",
            "/ask — retrieval diagnostics",
            "Grounding + confidence badge",
            "Draft vs revised disclosure",
            "/skills — per-dept export",
            "/metrics — AMD live dashboard",
            "/slack — MCP control panel",
        ]),
        ("Intelligence layer", C["purple"], HexColor("#1a0d23"), [
            "Atomic unit extraction (strict JSON)",
            "Entity kind taxonomy (7 types)",
            "Relationship verb extraction",
            "Confidence scoring per unit",
            "conflictsWith back-references",
            "Disputed badge in UI",
            "Temporal intent detection",
            "Knowledge gap punch list",
            "Per-dept SKILLS.md segmentation",
            "Agent Rules (≥0.75 conf units)",
        ]),
    ]
    x = 40
    for title, border_c, bg_c, items in cols:
        rounded_card(c, x, y, cw, ch, fill_color=bg_c, border_color=border_c)
        fill(c, border_c)
        c.setFont(FONT_BOLD, 12)
        c.drawString(x + 16, y + ch - 26, title)
        check_list(c, x + 16, y + 14, cw - 32, ch - 54, items, base_size=9.5, leading=14.5)
        x += cw + 15


def slide_compare(c):
    bg(c); topline(c, "Market")
    h4(c, 40, 480, "Competitive landscape")
    h2(c, 40, 442, "The capabilities no incumbent ships.",
       accent_words=["no incumbent ships."], size=24)

    rounded_card(c, 40, 100, PAGE_W - 80, 310, fill_color=C["card"], border_color=C["border"])

    rows = [
        ("Reconciliation / supersession",   "x", "x", "x", "v"),
        ("Directed knowledge graph",        "x", "x", "x", "v"),
        ("Conflict surfacing (Disputed)",   "x", "x", "x", "v"),
        ("Knowledge gap detection",         "x", "x", "x", "v"),
        ("VLM multimodal ingestion",        "x", "x", "p", "v"),
        ("Agent-loadable SKILLS.md",        "x", "x", "x", "v"),
        ("Self-hostable / open source",     "x", "x", "x", "v"),
    ]
    cols_x = [60, 480, 580, 680, 800]
    headers = ["CAPABILITY", "GLEAN", "NOTION AI", "COPILOT", "BRAINOS"]
    # header
    fill(c, C["dim"])
    c.setFont(FONT_BOLD, 9)
    for i, hdr in enumerate(headers):
        col = C["accent"] if hdr == "BRAINOS" else C["dim"]
        fill(c, col)
        if i == 0:
            c.drawString(cols_x[i], 380, hdr)
        else:
            c.drawCentredString(cols_x[i] + 30, 380, hdr)
    stroke(c, C["border"], 0.5)
    c.line(60, 372, PAGE_W - 60, 372)

    yy = 350
    for row in rows:
        label = row[0]
        marks = row[1:]
        fill(c, C["text"])
        c.setFont(FONT, 10)
        c.drawString(cols_x[0], yy, label)
        for i, mk in enumerate(marks):
            cx = cols_x[i + 1] + 30
            if mk == "v":
                fill(c, C["good"])
                c.setFont(FONT_BOLD, 14)
                c.drawCentredString(cx, yy, "✓")
            elif mk == "x":
                fill(c, C["bad"])
                c.setFont(FONT_BOLD, 14)
                c.drawCentredString(cx, yy, "✗")
            else:
                fill(c, HexColor("#eab308"))
                c.setFont(FONT_BOLD, 8)
                c.drawCentredString(cx, yy, "PARTIAL")
        yy -= 30

    fill(c, C["dim"])
    c.setFont(FONT_OBL, 9)
    c.drawString(40, 70, "Who needs this first: regulated industries (defense, healthcare, EU fintech)  ·  AI-native startups  ·  ops-heavy scale-ups.")


def slide_closing(c):
    bg(c)
    # Soft glow
    fill(c, C["accent"])
    c.setFillAlpha(0.08)
    c.circle(PAGE_W / 2, PAGE_H / 2 + 20, 280, stroke=0, fill=1)
    c.setFillAlpha(1.0)

    fill(c, C["white"])
    c.setFont(FONT_BOLD, 38)
    c.drawCentredString(PAGE_W / 2, 380, "Five minutes from a cold codebase to an")
    fill(c, C["accent"])
    c.drawCentredString(PAGE_W / 2, 332, "agent that knows the company.")

    fill(c, C["dim"])
    c.setFont(FONT, 12)
    c.drawCentredString(PAGE_W / 2, 290,
        "That's a company brain. Built on AMD MI300X. Open source. Ready for the next 99 companies.")

    # URL blocks
    blocks = [
        ("LIVE DEMO", "129.212.176.117:3000"),
        ("SOURCE",    "github.com/vamshinr/BrainOS"),
    ]
    bw, bh = 240, 70
    gap = 30
    total = bw * 2 + gap
    bx = (PAGE_W - total) / 2
    by = 175
    for label, url in blocks:
        rounded_card(c, bx, by, bw, bh, fill_color=HexColor("#2a1408"), border_color=C["accent"])
        fill(c, C["accent"])
        c.setFont(FONT_BOLD, 9)
        c.drawCentredString(bx + bw / 2, by + bh - 22, label)
        fill(c, C["white"])
        c.setFont(FONT_MONOB, 13)
        c.drawCentredString(bx + bw / 2, by + 18, url)
        bx += bw + gap

    # tag pills
    pills = [
        ("AMD MI300X",     C["amd"],          C["white"]),
        ("open source",    C["accent"],       HexColor("#000000")),
        ("self-hostable",  C["blue"],         C["white"]),
        ("vendor-neutral", C["good"],         HexColor("#000000")),
        ("Track 1 + 3",    C["purple"],       C["white"]),
    ]
    c.setFont(FONT_BOLD, 8)
    widths = [c.stringWidth(t.upper(), FONT_BOLD, 8) + 18 for t, _, _ in pills]
    pgap = 8
    total = sum(widths) + pgap * (len(pills) - 1)
    px = (PAGE_W - total) / 2
    py = 130
    for (text, bgc, fgc), w in zip(pills, widths):
        fill(c, bgc)
        c.roundRect(px, py, w, 16, 8, stroke=0, fill=1)
        fill(c, fgc)
        c.setFont(FONT_BOLD, 8)
        c.drawCentredString(px + w / 2, py + 5, text.upper())
        px += w + pgap

    fill(c, C["dim"])
    c.setFont(FONT, 9)
    c.drawCentredString(PAGE_W / 2, 90, "Noel  ·  Rajveer  ·  Vamshi  ·  AMD Hackathon 2026")


# ── build ────────────────────────────────────────────────────────────────────
SLIDES = [
    slide_cover,
    slide_problem,
    slide_solution,
    slide_why_matters,
    slide_dashboard_hero,
    slide_not_rag,
    slide_four_agents,
    slide_reconciliation,
    slide_features_examples,
    slide_ask,
    slide_skills,
    slide_slack_action,
    slide_amd,
    slide_compare,
    slide_closing,
]


def main():
    c = canvas.Canvas(str(OUT), pagesize=(PAGE_W, PAGE_H))
    c.setTitle("BrainOS — AMD Hackathon 2026")
    c.setAuthor("Noel · Rajveer · Vamshi")
    c.setSubject("Company Brain — built on AMD MI300X")
    c.setKeywords("BrainOS, AMD MI300X, knowledge graph, multi-agent, hackathon, RAG, SKILLS.md")
    total = len(SLIDES)
    for i, slide_fn in enumerate(SLIDES, start=1):
        slide_fn(c)
        # only put a footer (with page #) on non-cover/closing slides
        if i not in (1, total):
            footline(c, i, total)
        c.showPage()
    c.save()
    print(f"Wrote {OUT}  ({OUT.stat().st_size/1024:.1f} KB)")


if __name__ == "__main__":
    main()
