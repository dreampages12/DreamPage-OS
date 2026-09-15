from __future__ import annotations

import os
import re
from typing import Any, Dict, Iterable, List, Sequence, Tuple

from PIL import Image, ImageDraw, ImageFont, ImageFilter


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_HIGHLIGHT_FONT = os.path.join(SCRIPT_DIR, "Georgia Bold.ttf")

WordRun = Tuple[str, ImageFont.FreeTypeFont]
Line = Tuple[List[WordRun], float]


def _font_path(font: ImageFont.FreeTypeFont) -> str | None:
    return getattr(font, "path", None) or getattr(font, "font", None)


def _load_font_like(font: ImageFont.FreeTypeFont, size: int) -> ImageFont.FreeTypeFont:
    path = _font_path(font)
    if path:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            pass
    return font


def _load_highlight_font(size: int, fallback: ImageFont.FreeTypeFont) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(DEFAULT_HIGHLIGHT_FONT, size)
    except Exception:
        return fallback


def _clean_word(word: str) -> str:
    return re.sub(r"^[^\wÆØÅæøå]+|[^\wÆØÅæøå]+$", "", word, flags=re.UNICODE).lower()


def _measure_runs(draw: ImageDraw.ImageDraw, runs: Sequence[WordRun]) -> float:
    return sum(draw.textlength(text, font=font) for text, font in runs)


def _make_line(words: Sequence[str], fonts: Sequence[ImageFont.FreeTypeFont], start: int, end: int) -> Line:
    runs: List[WordRun] = []
    for idx in range(start, end):
        prefix = "" if idx == start else " "
        runs.append((prefix + words[idx], fonts[idx]))
    return runs, 0.0


def _line_width(draw: ImageDraw.ImageDraw, line: Line) -> float:
    runs, cached_width = line
    if cached_width:
        return cached_width
    return _measure_runs(draw, runs)


def _wrap_words_balanced(
    draw: ImageDraw.ImageDraw,
    words: Sequence[str],
    fonts: Sequence[ImageFont.FreeTypeFont],
    max_width: int,
) -> List[Line]:
    if not words:
        return []

    n = len(words)
    widths = [draw.textlength(word, font=font) for word, font in zip(words, fonts)]
    space_width = draw.textlength(" ", font=fonts[0]) if fonts else 0

    line_width: Dict[Tuple[int, int], float] = {}
    for i in range(n):
        width = 0.0
        for j in range(i, n):
            width += widths[j]
            if j > i:
                width += space_width
            line_width[(i, j + 1)] = width
            if width > max_width and j > i:
                break

    dp = [float("inf")] * (n + 1)
    next_break = [n] * (n + 1)
    dp[n] = 0.0

    for i in range(n - 1, -1, -1):
        for j in range(i + 1, n + 1):
            width = line_width.get((i, j))
            if width is None:
                break
            if width > max_width and j > i + 1:
                break

            count = j - i
            is_last = j == n
            ragged = max_width - min(width, max_width)
            cost = (ragged / max(max_width, 1)) ** 2

            if count == 1 and n > 2:
                cost += 9.0 if is_last else 5.0
            if is_last and width < max_width * 0.36 and n > 4:
                cost += 4.0
            if not is_last and width < max_width * 0.42 and count <= 2:
                cost += 1.6

            total = cost + dp[j]
            if total < dp[i]:
                dp[i] = total
                next_break[i] = j

    lines: List[Line] = []
    i = 0
    while i < n:
        j = next_break[i]
        if j <= i:
            j = min(i + 1, n)
        runs, _ = _make_line(words, fonts, i, j)
        lines.append((runs, _measure_runs(draw, runs)))
        i = j

    return _repair_orphans(draw, lines, max_width)


_LEADING_DASHES = {"–", "—", "-"}


def _wrap_words_even(
    draw: ImageDraw.ImageDraw,
    words: Sequence[str],
    fonts: Sequence[ImageFont.FreeTypeFont],
    max_width: int,
) -> List[Line]:
    """Linjedeling som jevner ut linjebreddene i stedet for aa fylle hver linje.

    _wrap_words_balanced pakker linjene saa fulle som mulig, noe som gir et
    skjevt linjefall paa sentrert tekst (naesten full linje, full linje, kort
    linje). Her laaser vi antall linjer til det graadige minimumet og fordeler
    ordene slik at summen av kvadrert slakk blir minst - med likt antall linjer
    betyr det at linjene blir omtrent like brede.
    """
    n = len(words)
    if n == 0:
        return []

    cache: Dict[Tuple[int, int], Line] = {}

    def line(i: int, j: int) -> Line:
        key = (i, j)
        if key not in cache:
            runs, _ = _make_line(words, fonts, i, j)
            cache[key] = (runs, _measure_runs(draw, runs))
        return cache[key]

    greedy = _wrap_words_balanced(draw, words, fonts, max_width)
    target = len(greedy)
    if target <= 1:
        return greedy

    INF = float("inf")
    # cost[l][j]: minste kostnad for de j foerste ordene fordelt paa l linjer.
    cost = [[INF] * (n + 1) for _ in range(target + 1)]
    back = [[0] * (n + 1) for _ in range(target + 1)]
    cost[0][0] = 0.0

    for l in range(1, target + 1):
        for j in range(1, n + 1):
            best = INF
            best_i = None
            for i in range(j - 1, l - 2, -1):
                if i < 0 or cost[l - 1][i] == INF:
                    continue
                width = line(i, j)[1]
                if width > max_width and j - i > 1:
                    break
                slack = max_width - width
                penalty = 0.0
                if words[i].strip() in _LEADING_DASHES:
                    # En tankestrek alene foerst paa linjen ser ut som et
                    # feilaktig linjeskift; flytt heller et ord ned.
                    penalty = (max_width * 0.10) ** 2
                candidate = cost[l - 1][i] + slack * slack + penalty
                if candidate < best:
                    best = candidate
                    best_i = i
            cost[l][j] = best
            if best_i is not None:
                back[l][j] = best_i

    if cost[target][n] == INF:
        return greedy

    cuts: List[Tuple[int, int]] = []
    j = n
    for l in range(target, 0, -1):
        i = back[l][j]
        cuts.append((i, j))
        j = i
    cuts.reverse()

    return [line(i, j) for i, j in cuts]


def _repair_orphans(draw: ImageDraw.ImageDraw, lines: List[Line], max_width: int) -> List[Line]:
    if len(lines) < 2:
        return lines

    changed = True
    while changed:
        changed = False
        for idx in range(1, len(lines)):
            runs, width = lines[idx]
            prev_runs, prev_width = lines[idx - 1]
            visible_words = [text.strip() for text, _ in runs if text.strip()]
            if len(visible_words) != 1 or len(prev_runs) <= 1:
                continue

            moved_text, moved_font = prev_runs[-1]
            moved_word = moved_text.strip()
            new_prev = prev_runs[:-1]
            new_current = [(moved_word, moved_font)] + [(" " + text.strip(), font) for text, font in runs]
            new_prev_width = _measure_runs(draw, new_prev)
            new_current_width = _measure_runs(draw, new_current)

            if new_current_width <= max_width and new_prev_width >= max_width * 0.28:
                lines[idx - 1] = (new_prev, new_prev_width)
                lines[idx] = (new_current, new_current_width)
                changed = True
                break

    return lines


def _layout_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    box: Tuple[int, int, int, int],
    font: ImageFont.FreeTypeFont,
    line_spacing: int,
    highlights: Iterable[str] | None,
    even_wrap: bool = False,
) -> Tuple[List[Tuple[List[Line], bool]], int]:
    x1, y1, x2, y2 = box
    max_width = x2 - x1
    hl_set = {_clean_word(h.strip()) for h in (highlights or []) if h.strip()}
    highlight_font = _load_highlight_font(font.size, font)
    paragraphs: List[Tuple[List[Line], bool]] = []
    total_height = 0

    for para in text.split("\n"):
        para = para.strip()
        if not para:
            paragraphs.append(([], True))
            total_height += font.size + line_spacing
            continue

        words = [w for w in para.split(" ") if w]
        fonts = [highlight_font if _clean_word(word) in hl_set else font for word in words]
        if even_wrap:
            lines = _wrap_words_even(draw, words, fonts, max_width)
        else:
            lines = _wrap_words_balanced(draw, words, fonts, max_width)
        paragraphs.append((lines, False))
        total_height += len(lines) * (font.size + line_spacing) + line_spacing

    return paragraphs, total_height


def _draw_gradient_word(
    img: Image.Image,
    draw: ImageDraw.ImageDraw,
    text: str,
    x: int,
    y: int,
    font: ImageFont.FreeTypeFont,
    colors: Tuple[Tuple[int, int, int], Tuple[int, int, int]],
    shadow: Tuple[int, int, int] | None = None,
) -> None:
    mask = Image.new("L", img.size, 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.text((x, y), text, font=font, fill=255)

    if shadow:
        shadow_mask = mask.filter(ImageFilter.GaussianBlur(2))
        shadow_layer = Image.new("RGBA", img.size, (*shadow, 120))
        img.paste(shadow_layer, (0, 0), shadow_mask)

    bbox = draw.textbbox((x, y), text, font=font)
    x0, y0, x1, y1 = bbox
    height = max(1, y1 - y0)

    grad = Image.new("RGBA", img.size, (0, 0, 0, 0))
    grad_draw = ImageDraw.Draw(grad)
    for yy in range(y0, y1):
        t = (yy - y0) / height
        color = (
            int(colors[0][0] + (colors[1][0] - colors[0][0]) * t),
            int(colors[0][1] + (colors[1][1] - colors[0][1]) * t),
            int(colors[0][2] + (colors[1][2] - colors[0][2]) * t),
            255,
        )
        grad_draw.line([(x0, yy), (x1, yy)], fill=color)

    img.paste(grad, (0, 0), mask)


def _color_luminance(color: Any) -> float:
    if isinstance(color, str) and color.startswith("#") and len(color) >= 7:
        try:
            r = int(color[1:3], 16)
            g = int(color[3:5], 16)
            b = int(color[5:7], 16)
            return 0.2126 * r + 0.7152 * g + 0.0722 * b
        except ValueError:
            pass
    if isinstance(color, tuple) and len(color) >= 3:
        r, g, b = color[:3]
        return 0.2126 * r + 0.7152 * g + 0.0722 * b
    return 255


def _shadow_fill_for(color: Any, alpha: int) -> Tuple[int, int, int, int]:
    if _color_luminance(color) > 150:
        return (0, 0, 0, alpha)
    return (255, 255, 255, max(55, int(alpha * 0.75)))


def draw_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    box: Tuple[int, int, int, int],
    font: ImageFont.FreeTypeFont,
    color: str = "#FFFFFF",
    stroke_color: str = "#000000",
    line_spacing: int = 10,
    highlights: Iterable[str] | None = None,
    gradient: Dict[str, Any] | None = None,
    img: Image.Image | None = None,
    align: str = "left",
    shadow: bool = True,
    shadow_offset: int = 3,
    shadow_blur: int = 2,
    shadow_alpha: int = 95,
    even_wrap: bool = False,
) -> None:
    x1, y1, x2, y2 = box
    max_width = x2 - x1
    max_height = y2 - y1

    current_font = font
    current_spacing = line_spacing
    paragraphs, total_height = _layout_text(draw, text, box, current_font, current_spacing, highlights, even_wrap)

    min_size = max(16, int(font.size * 0.78))
    while total_height > max_height and current_font.size > min_size:
        next_size = current_font.size - 1
        current_font = _load_font_like(current_font, next_size)
        current_spacing = max(3, int(line_spacing * (next_size / max(font.size, 1))))
        paragraphs, total_height = _layout_text(draw, text, box, current_font, current_spacing, highlights, even_wrap)

    def paint_text(
        target_draw: ImageDraw.ImageDraw,
        target_img: Image.Image | None,
        *,
        fill,
        x_shift: int = 0,
        y_shift: int = 0,
        allow_gradient: bool = True,
    ) -> None:
        y = y1 + y_shift
        for lines, is_blank in paragraphs:
            if is_blank:
                y += current_font.size + current_spacing
                continue

            for runs, line_width in lines:
                if align == "center":
                    x = x1 + max(0, int((max_width - line_width) / 2))
                elif align == "right":
                    x = x2 - int(line_width)
                else:
                    x = x1
                x += x_shift

                for piece, piece_font in runs:
                    if allow_gradient and gradient and target_img is not None:
                        _draw_gradient_word(
                            target_img,
                            target_draw,
                            piece,
                            int(x),
                            int(y),
                            piece_font,
                            gradient.get("colors", ((30, 60, 120), (90, 110, 160))),
                            gradient.get("shadow"),
                        )
                    else:
                        target_draw.text(
                            (int(x), int(y)),
                            piece,
                            font=piece_font,
                            fill=fill,
                            stroke_width=0,
                            stroke_fill=stroke_color,
                        )
                    x += target_draw.textlength(piece, font=piece_font)

                y += current_font.size + current_spacing

            y += current_spacing

    if shadow and gradient is None and img is not None:
        offset = max(1, int(shadow_offset))
        blur = max(0, int(shadow_blur))
        shadow_layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
        shadow_draw = ImageDraw.Draw(shadow_layer)
        paint_text(
            shadow_draw,
            shadow_layer,
            fill=_shadow_fill_for(color, shadow_alpha),
            x_shift=offset,
            y_shift=offset,
            allow_gradient=False,
        )
        if blur:
            shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(blur))
        img.alpha_composite(shadow_layer)

    paint_text(draw, img, fill=color, allow_gradient=True)
