#!/usr/bin/env python3
import bisect, math, os, shutil, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).parent

# ── Layout constants ───────────────────────────────────────────────────────────
PANE_HEADER_H = 26    # height of bottom-panel title bars in pixels
GAME_HEADER_H = 36    # height of game panel header — DOOMQL title only
GRAPH_STRIP_H = 100   # height of the FPS/tick-rate graph strip at bottom of video


# ── Font helpers ───────────────────────────────────────────────────────────────
def _find_font(size, mono=True):
    candidates = (
        ["/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
         "/usr/share/fonts/TTF/DejaVuSansMono.ttf",
         "/usr/share/fonts/truetype/freefont/FreeMono.ttf",
         "/System/Library/Fonts/Menlo.ttc",
         "/Library/Fonts/Courier New.ttf"]
        if mono else
        ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
         "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
         "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
         "/System/Library/Fonts/Helvetica.ttc",
         "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
         "/usr/share/fonts/TTF/DejaVuSansMono.ttf"]
    )
    from PIL import ImageFont
    for p in candidates:
        try:
            return ImageFont.truetype(p, size)
        except (IOError, OSError):
            pass
    return ImageFont.load_default()


def _text_size(draw_or_font, text, font):
    bb = draw_or_font.textbbox((0, 0), text, font=font)
    return bb[2] - bb[0], bb[3] - bb[1]


# ── HUD helpers ────────────────────────────────────────────────────────────────
def _doom_metric_color(ms):
    """Green / yellow / red based on latency — mirrors the DOOM health-bar palette."""
    if ms is None:   return (90, 90, 90)
    if ms < 100:     return (75, 200, 75)
    if ms < 500:     return (215, 190, 55)
    return (220, 65, 45)


def _doom_face(action):
    """Tiny ASCII face that changes with the player's action — homage to the DOOM HUD."""
    a = (action or "").upper()
    if a == "X":          return ">:-D"   # grinning while shooting
    if a == "W":          return ":-]"    # marching forward
    if a == "S":          return "[-:"    # backing off
    if a in ("A", "D"):   return ";-)"    # looking around
    return ":-|"                          # idle / waiting


# ── Panel drawing ──────────────────────────────────────────────────────────────
def _draw_panel_header(draw, x0, y0, pw, title, font, right_label=None, right_color=None,
                       bg=(38, 12, 12), fg=(208, 172, 110)):
    """Filled title bar across the top of a panel."""
    draw.rectangle([x0, y0, x0 + pw - 1, y0 + PANE_HEADER_H - 1], fill=bg)
    tw, th = _text_size(draw, title, font)
    draw.text((x0 + (pw - tw) // 2, y0 + (PANE_HEADER_H - th) // 2), title, fill=fg, font=font)
    if right_label:
        rw, rh = _text_size(draw, right_label, font)
        draw.text((x0 + pw - rw - 10, y0 + (PANE_HEADER_H - rh) // 2),
                  right_label, fill=right_color or fg, font=font)


def _draw_key(draw, x, y, w, h, label, sublabel, active, font_main, font_sub):
    # DOOM-style chunky key: sharp corners, top/left highlight, bottom/right shadow
    if active:
        bg, hi, sh, fg = (185, 22, 22), (240, 80, 70), (80, 8, 8), (255, 230, 180)
    else:
        bg, hi, sh, fg = (30, 26, 24), (62, 54, 44), (10, 8, 8), (80, 72, 60)
    draw.rectangle([x, y, x+w, y+h], fill=bg)
    draw.line([(x, y), (x+w-1, y)],   fill=hi, width=2)   # top
    draw.line([(x, y), (x, y+h-1)],   fill=hi, width=2)   # left
    draw.line([(x, y+h), (x+w, y+h)], fill=sh, width=2)   # bottom
    draw.line([(x+w, y), (x+w, y+h)], fill=sh, width=2)   # right
    if sublabel:
        tw, th = _text_size(draw, label, font_main)
        sw, sh = _text_size(draw, sublabel, font_sub)
        gap = 4
        total_h = th + gap + sh
        draw.text((x+(w-tw)//2, y+(h-total_h)//2),        label,    fill=fg, font=font_main)
        draw.text((x+(w-sw)//2, y+(h-total_h)//2+th+gap), sublabel, fill=fg, font=font_sub)
    else:
        tw, th = _text_size(draw, label, font_main)
        draw.text((x+(w-tw)//2, y+(h-th)//2), label, fill=fg, font=font_main)


def _draw_keyboard_panel(draw, x0, y0, pw, ph, action, font_key, font_fire, font_sub, font_metric):
    """WASD + FIRE keyboard in the given pane rectangle."""
    active = (action or "").upper()

    _draw_panel_header(draw, x0, y0, pw, "-=[ INPUT ]=-", font_sub)
    y0 += PANE_HEADER_H
    ph -= PANE_HEADER_H

    gap      = max(6, ph // 55)
    face_str = _doom_face(action)
    # Use the widest possible face for layout so keys never shift between frames
    _all_faces = [">:-D", ":-]", "[-:", ";-)", ":-|"]
    fw_face  = max(_text_size(draw, f, font_metric)[0] for f in _all_faces)
    fh_face  = _text_size(draw, face_str, font_metric)[1]
    ksz      = max(20, (ph - gap * 4) // 4)

    blk_w    = ksz * 3 + gap * 2
    blk_h    = ksz * 2 + gap
    fire_sz  = blk_h
    blk_total_h = blk_h + gap * 2 + fire_sz

    # Keys block + face side-by-side, centred as a unit using stable max face width
    inner_w = blk_w + gap * 2 + fw_face
    sx = x0 + max(0, (pw - inner_w) // 2)
    sy = y0 + max(0, (ph - blk_total_h) // 2)

    _draw_key(draw, sx + ksz + gap,       sy,             ksz, ksz, "W", None, active=="W", font_key, font_sub)
    _draw_key(draw, sx,                   sy + ksz + gap, ksz, ksz, "A", None, active=="A", font_key, font_sub)
    _draw_key(draw, sx + ksz + gap,       sy + ksz + gap, ksz, ksz, "S", None, active=="S", font_key, font_sub)
    _draw_key(draw, sx + 2 * (ksz + gap), sy + ksz + gap, ksz, ksz, "D", None, active=="D", font_key, font_sub)

    fy = sy + blk_h + gap * 2
    fx = sx + (blk_w - fire_sz) // 2
    _draw_key(draw, fx, fy, fire_sz, fire_sz, "FIRE", "[X]", active=="X", font_fire, font_sub)

    # Face to the right of keys, vertically centred on the whole block
    face_color = (220, 65, 45) if active == "X" else (148, 130, 90)
    draw.text((sx + blk_w + gap * 2, sy + (blk_total_h - fh_face) // 2),
              face_str, fill=face_color, font=font_metric)


def _draw_database_panel(draw, x0, y0, pw, ph, db_name, font_sub, font_dbname):
    """Left column: DATABASE label + large DB name."""
    _draw_panel_header(draw, x0, y0, pw, "-=[ DATABASE ]=-", font_sub)
    y0 += PANE_HEADER_H
    ph -= PANE_HEADER_H
    if db_name and font_dbname:
        dw, dh = _text_size(draw, db_name.upper(), font_dbname)
        draw.text((x0 + max(8, (pw - dw) // 2), y0 + max(4, (ph - dh) // 2)),
                  db_name.upper(), fill=(228, 200, 148), font=font_dbname)


def _draw_dewitt_bars(draw, x0, y0, w, h, font_sub, notice=None):
    """Document-style redaction: stacked black bars like a declassified NSA filing."""
    draw.rectangle([x0, y0, x0 + w - 1, y0 + h - 1], fill=(26, 20, 16))
    bar_h  = max(7, (h - 16) // 7)
    gap    = max(3, bar_h // 3)
    step   = bar_h + gap
    n_bars = max(1, (h - 16) // step)
    margin = max(12, w // 16)
    # Vary left/right indents per bar so it looks like redacted lines of differing length
    offsets = [(0, 0), (8, 14), (4, 6), (16, 4), (0, 10), (6, 0), (12, 8)]
    total_h = n_bars * step - gap
    start_y = y0 + (h - total_h) // 2
    for i in range(n_bars):
        ol, or_ = offsets[i % len(offsets)]
        by = start_y + i * step
        draw.rectangle([x0 + margin + ol, by, x0 + w - margin - or_, by + bar_h],
                       fill=(0, 0, 0))
    if notice:
        nw, nh = _text_size(draw, notice, font_sub)
        draw.text((x0 + w - nw - 6, y0 + h - nh - 3),
                  notice, fill=(60, 48, 36), font=font_sub)


def _draw_metrics_panel(draw, x0, y0, pw, ph, font_sub, font_metric, fps_rate, tick_rate,
                        redact_metrics=False):
    """Server latency metrics column. fps_rate and tick_rate are rolling rates in Hz."""
    _draw_panel_header(draw, x0, y0, pw, "-=[ METRICS ]=-", font_sub)
    y0 += PANE_HEADER_H
    ph -= PANE_HEADER_H

    entries = [
        ("FPS", fps_rate),
        ("TPS", tick_rate),
    ]
    row_h   = ph // len(entries)

    if redact_metrics:
        draw.rectangle([x0, y0, x0 + pw - 1, y0 + ph - 1], fill=(26, 20, 16))
        probe = "00.0"
        _, vh = _text_size(draw, probe, font_metric)
        for i, (label, _) in enumerate(entries):
            ry = y0 + i * row_h
            lw, lh = _text_size(draw, label, font_sub)
            inner_h = lh + 6 + vh
            label_y = ry + (row_h - inner_h) // 2
            draw.text((x0 + (pw - lw) // 2, label_y),
                      label, fill=(75, 58, 38), font=font_sub)
            bar_y = label_y + lh + 4
            pad   = max(6, pw // 6)
            draw.rectangle([x0 + pad, bar_y, x0 + pw - pad, bar_y + vh + 4],
                           fill=(0, 0, 0))
        nw, nh = _text_size(draw, "DeWitt Clause", font_sub)
        draw.text((x0 + (pw - nw) // 2, y0 + ph - nh - 4),
                  "DeWitt Clause", fill=(55, 42, 28), font=font_sub)
        return

    for i, (label, rate) in enumerate(entries):
        ry    = y0 + i * row_h
        # colour using equivalent ms for threshold logic
        ms    = round(1000.0 / rate, 1) if rate else None
        color = _doom_metric_color(ms)
        val   = f"{rate:.1f}" if rate is not None else "--"
        lw, lh = _text_size(draw, label, font_sub)
        vw, vh = _text_size(draw, val,   font_metric)
        inner_h = lh + 6 + vh
        draw.text((x0 + (pw - lw) // 2, ry + (row_h - inner_h) // 2),
                  label, fill=(128, 100, 60), font=font_sub)
        draw.text((x0 + (pw - vw) // 2, ry + (row_h - inner_h) // 2 + lh + 6),
                  val,   fill=color,         font=font_metric)


def _draw_map_panel(draw, x0, y0, pw, ph, mobs, map_cache, map_bounds, font_sub):
    """Top-down minimap column — the DB's current world model, independent of rendering."""
    _draw_panel_header(draw, x0, y0, pw, "-=[ WORLD STATE ]=-", font_sub)
    y0 += PANE_HEADER_H
    ph -= PANE_HEADER_H

    if not map_cache or not map_bounds:
        return

    min_x, max_x, min_y, max_y = map_bounds
    tiles_w = max_x - min_x + 1
    tiles_h = max_y - min_y + 1

    avail_w = pw - 16
    avail_h = ph - 8
    tile_px = max(1, min(avail_w // tiles_w, avail_h // tiles_h))

    ox = x0 + (pw - tile_px * tiles_w) // 2
    oy = y0 + 4 + (avail_h - tile_px * tiles_h) // 2

    tile_color = {'#': (55, 28, 22), '.': (18, 26, 18), 'R': (18, 38, 18)}
    for (tx, ty, tile) in map_cache:
        px = ox + (tx - min_x) * tile_px
        py = oy + (ty - min_y) * tile_px
        draw.rectangle([px, py, px + tile_px - 1, py + tile_px - 1],
                       fill=tile_color.get(tile, (18, 18, 18)))

    if mobs:
        icon_color = {'1': (220, 60, 60), '2': (220, 200, 60), '*': (240, 240, 180)}
        for row in mobs:
            mx, my, icon = float(row[0]), float(row[1]), row[2]
            mdir = float(row[3]) if len(row) > 3 and row[3] is not None else None
            px = int(ox + (mx - min_x) * tile_px)
            py = int(oy + (my - min_y) * tile_px)
            r  = max(2, tile_px // 2) if icon != '*' else max(1, tile_px // 4)
            color = icon_color.get(icon, (160, 160, 160))
            draw.ellipse([px - r, py - r, px + r, py + r], fill=color)
            # Direction arrow for players only
            if mdir is not None and icon in ('1', '2'):
                alen = max(r * 3, tile_px + 2)
                ex = px + int(math.cos(mdir) * alen)
                ey = py + int(math.sin(mdir) * alen)
                draw.line([(px, py), (ex, ey)], fill=color, width=max(1, r // 2))


def _draw_graph_strip(draw, x0, y0, w, h, t_ms, total_ms,
                      fps_series, tick_series, font_sub,
                      redact_metrics=False):
    """Full-width performance graph: rolling FPS (yellow) and tick rate (red)."""
    _draw_panel_header(draw, x0, y0, w, "-=[ PERFORMANCE ]=-", font_sub)
    y0 += PANE_HEADER_H
    h  -= PANE_HEADER_H

    if redact_metrics:
        _draw_dewitt_bars(draw, x0, y0, w, h, font_sub,
                          notice="DeWitt Clause — performance data withheld from publication")
        return

    draw.rectangle([x0, y0, x0 + w - 1, y0 + h - 1], fill=(8, 6, 6))

    pad_l, pad_r, pad_t, pad_b = 44, 12, 6, 16
    gx0, gy0 = x0 + pad_l, y0 + pad_t
    gx1, gy1 = x0 + w - pad_r, y0 + h - pad_b
    gw, gh   = gx1 - gx0, gy1 - gy0
    if gw < 4 or gh < 4:
        return

    # Y scale: auto-fit to visible peak, minimum 10
    visible_fps  = [v for t, v in fps_series  if t <= t_ms]
    visible_tick = [v for t, v in tick_series if t <= t_ms]
    y_max = max(10.0, max((visible_fps or [0]) + (visible_tick or [0])) * 1.15)

    # Subtle horizontal grid at 25 / 50 / 75 %
    grid_col = (30, 22, 22)
    for frac in (0.25, 0.5, 0.75):
        gy = int(gy1 - gh * frac)
        draw.line([(gx0, gy), (gx1, gy)], fill=grid_col, width=1)

    # Axes
    axis_col = (55, 38, 38)
    draw.rectangle([gx0, gy0, gx1, gy1], outline=axis_col)

    # Y labels (top / mid / zero)
    for frac, lbl in ((1.0, f"{y_max:.0f}"), (0.5, f"{y_max/2:.0f}"), (0.0, "0")):
        gy = int(gy1 - gh * frac)
        lw, lh = _text_size(draw, lbl, font_sub)
        draw.text((gx0 - lw - 4, gy - lh // 2), lbl, fill=(90, 70, 50), font=font_sub)

    def plot(series, color):
        pts = [(t, v) for t, v in series if t <= t_ms]
        if len(pts) < 2:
            return
        pixels = [
            (int(gx0 + gw * min(t, total_ms) / max(total_ms, 1)),
             int(gy1 - gh * min(v, y_max)    / y_max))
            for t, v in pts
        ]
        for i in range(len(pixels) - 1):
            draw.line([pixels[i], pixels[i + 1]], fill=color, width=2)
        # Bright dot at current tip
        draw.ellipse([pixels[-1][0]-2, pixels[-1][1]-2,
                      pixels[-1][0]+2, pixels[-1][1]+2], fill=color)

    plot(fps_series,  (195, 210, 55))   # yellow-green: FPS
    plot(tick_series, (220, 65,  45))   # DOOM red: tick rate

    # Current-time hairline
    cx = int(gx0 + gw * min(t_ms, total_ms) / max(total_ms, 1))
    draw.line([(cx, gy0), (cx, gy1)], fill=(140, 90, 55), width=1)

    # Progress bar — 3px strip along the very bottom of the strip
    prog = min(1.0, t_ms / max(total_ms, 1))
    px   = int(prog * w)
    by   = y0 + h - 3
    if px > 0:
        draw.rectangle([x0, by, x0 + px - 1, y0 + h - 1], fill=(175, 38, 38))
    if px < w:
        draw.rectangle([x0 + px, by, x0 + w - 1, y0 + h - 1], fill=(18, 10, 10))

    # Legend — top-right corner
    leg_y = y0 + 2
    for label, color in (("FPS", (195, 210, 55)), ("TICK/s", (220, 65, 45))):
        lw, lh = _text_size(draw, label, font_sub)
        leg_x  = gx1 - lw - 24
        draw.rectangle([leg_x - 18, leg_y + lh // 2 - 1, leg_x - 4, leg_y + lh // 2 + 1],
                       fill=color)
        draw.text((leg_x, leg_y), label, fill=color, font=font_sub)
        leg_y += lh + 4


# ── Frame compositor ───────────────────────────────────────────────────────────
def _render_one_frame(frame_rows, kbd_action, render_ms, tick_ms,
                      minimap_mobs, map_cache, map_bounds,
                      ascii_h, char_h, bottom_h, img_w,
                      font_ascii, font_key, font_fire, font_sub, font_metric,
                      db_name=None, game_w_natural=None, font_dbname=None,
                      redact_metrics=False,
                      fps_series=None, tick_series=None, t_ms=0, total_ms=10000):
    from PIL import Image, ImageDraw
    game_h  = GAME_HEADER_H + ascii_h
    panel_h = bottom_h - GRAPH_STRIP_H
    img_h   = game_h + bottom_h
    img     = Image.new("RGB", (img_w, img_h), (10, 8, 8))
    draw    = ImageDraw.Draw(img)
    sep     = (65, 20, 20)

    # Side-by-side layout: game view (left 62%) | world map (right 38%)
    # Map gets full game height → ~730×726 px instead of the old 576×248 px corner.
    game_col_w = img_w * 62 // 100
    map_col_w  = img_w - game_col_w

    # ── Game panel — rendered at natural char width then scaled to game_col_w ──
    gw    = game_w_natural if (game_w_natural and game_w_natural > 0) else game_col_w
    gsurf = Image.new("RGB", (gw, game_h), (10, 7, 7))
    gdraw = ImageDraw.Draw(gsurf)

    _draw_panel_header(gdraw, 0, 0, gw, "-=[ DOOMQL ]=-", font_sub)
    for i, row in enumerate(frame_rows):
        gdraw.text((4, GAME_HEADER_H + i * char_h), row, fill=(218, 200, 158), font=font_ascii)

    if gw != game_col_w:
        img.paste(gsurf.resize((game_col_w, game_h), Image.LANCZOS), (0, 0))
    else:
        img.paste(gsurf, (0, 0))

    # ── Game panel border (drawn on img after paste so it survives scaling) ─────
    draw.rectangle([0, 0, game_col_w - 1, game_h - 1], outline=sep, width=2)

    # ── World map — right column, full game height ────────────────────────────
    draw.line([(game_col_w, 0), (game_col_w, game_h)], fill=sep, width=2)
    _draw_map_panel(draw, game_col_w, 0, map_col_w, game_h,
                    minimap_mobs, map_cache, map_bounds, font_sub)

    # ── Bottom HUD strip: DATABASE | INPUT | METRICS | GRAPH ─────────────────
    col1_w = img_w * 22 // 100
    col2_w = img_w * 30 // 100
    col3_w = img_w - col1_w - col2_w
    c2     = col1_w
    c3     = col1_w + col2_w
    draw.line([(0, game_h), (img_w, game_h)], fill=sep, width=2)
    for cx in (c2, c3):
        draw.line([(cx, game_h), (cx, game_h + panel_h)], fill=sep, width=1)

    _draw_database_panel(draw, 0,  game_h, col1_w, panel_h, db_name, font_sub, font_dbname)
    _draw_keyboard_panel(draw, c2, game_h, col2_w, panel_h, kbd_action, font_key, font_fire, font_sub, font_metric)
    fps_rate  = next((v for t, v in reversed(fps_series  or []) if t <= t_ms), None)
    tick_rate = next((v for t, v in reversed(tick_series or []) if t <= t_ms), None)
    _draw_metrics_panel(draw, c3, game_h, col3_w, panel_h, font_sub, font_metric, fps_rate, tick_rate,
                        redact_metrics=redact_metrics)

    # Full-width graph strip
    graph_y = game_h + panel_h
    draw.line([(0, graph_y), (img_w, graph_y)], fill=sep, width=1)
    _draw_graph_strip(draw, 0, graph_y, img_w, GRAPH_STRIP_H,
                      t_ms, total_ms,
                      fps_series  or [],
                      tick_series or [],
                      font_sub,
                      redact_metrics=redact_metrics)

    return img


# ── Encoder ────────────────────────────────────────────────────────────────────
def frames_to_video(frames, output_path, map_cache=None, map_bounds=None,
                    minimap_frames=None, action_frames=None, db_name=None,
                    redact_metrics=False):
    """Render captured frames to an H.264 MP4 using Pillow + ffmpeg.
    Returns True on success, False if dependencies are missing or encoding fails."""
    if not frames:
        return False
    try:
        from PIL import Image as _Img, ImageDraw, ImageFont  # noqa: F401
    except ImportError:
        print("  [skip video] Pillow not installed  →  pip install Pillow")
        return False

    if not shutil.which("ffmpeg"):
        print("  [skip video] ffmpeg not found in PATH")
        return False

    _tmp = _Img.new("RGB", (1, 1))
    _d   = ImageDraw.Draw(_tmp)

    # Fixed 16:9 output.  Find the largest font that fits 64 rows in ≤80% of height,
    # leaving ≥200px for the bottom panels.
    TARGET_W, TARGET_H = 1920, 1080
    n_rows = len(frames[0]["frame"])
    font_ascii, ch = _find_font(7, mono=True), 8
    for fs in range(22, 6, -1):
        ftmp = _find_font(fs, mono=True)
        _, fh = _text_size(_d, "Mg", ftmp)
        if fh > 0 and fh * n_rows + GAME_HEADER_H + 200 <= TARGET_H:
            font_ascii, ch = ftmp, fh
            break

    cw = _text_size(_d, "M", font_ascii)[0]
    if cw < 1: cw = 6

    max_chars      = max(len(r) for f in frames for r in f["frame"])  # full row, no clip
    game_w_natural = max_chars * cw + 16   # natural render width at char metrics
    ascii_h        = n_rows * ch
    game_h         = GAME_HEADER_H + ascii_h
    bottom_h       = TARGET_H - game_h     # fills remainder → total = exactly TARGET_H
    img_w          = TARGET_W & ~1         # even for H.264

    gap_approx  = max(6, bottom_h // 55)
    ksz_approx  = max(20, (bottom_h - PANE_HEADER_H - 30 - gap_approx * 5) // 4)
    font_key    = _find_font(max(16, ksz_approx * 2 // 5), mono=False)
    font_fire   = _find_font(max(16, ksz_approx * 2 // 5), mono=False)
    font_sub    = _find_font(max(14, ksz_approx // 3),     mono=False)
    font_metric = _find_font(max(20, ksz_approx * 2 // 3), mono=False)
    # DB name font — fills the left column; shrink if name is too wide
    col1_w_approx = img_w * 20 // 100
    _dbname_sz    = max(36, bottom_h * 3 // 10)
    font_dbname   = _find_font(_dbname_sz, mono=False)
    if db_name:
        _dw, _ = _text_size(_d, db_name.upper(), font_dbname)
        _max_w  = col1_w_approx - 16
        if _dw > _max_w:
            font_dbname = _find_font(max(14, int(_dbname_sz * _max_w / _dw)), mono=False)

    TARGET_FPS = 30
    total_ms   = frames[-1]["t"] + 800
    n_slots    = max(1, int(total_ms * TARGET_FPS / 1000))

    # Pre-build sorted timestamp lists for O(log n) per-slot lookup
    frame_times = [f["t"] for f in frames]
    mm_times    = [m["t"] for m in minimap_frames] if minimap_frames else []
    act_times   = [a["t"] for a in action_frames]  if action_frames  else []

    # Rolling 1-second window FPS and tick-rate series for the graph strip
    GRAPH_WINDOW_MS = 1000
    fps_series = []
    for i in range(len(frames)):
        t = frames[i]["t"]
        lo = bisect.bisect_left(frame_times, t - GRAPH_WINDOW_MS)
        window_ms = min(t + 1, GRAPH_WINDOW_MS)
        fps_series.append((t, (i - lo + 1) * 1000.0 / max(window_ms, 1)))

    tick_series = []
    for i, a in enumerate(action_frames or []):
        t = a["t"]
        lo = bisect.bisect_left(act_times, t - GRAPH_WINDOW_MS)
        window_ms = min(t + 1, GRAPH_WINDOW_MS)
        tick_series.append((t, (i - lo + 1) * 1000.0 / max(window_ms, 1)))

    with tempfile.TemporaryDirectory() as tmpdir:
        for slot in range(n_slots):
            t_ms = slot * 1000.0 / TARGET_FPS

            # Most recent game frame at or before t_ms
            fi = max(0, bisect.bisect_right(frame_times, t_ms) - 1)

            # Most recent minimap frame at or before t_ms — advances independently
            if mm_times:
                mmi     = max(0, bisect.bisect_right(mm_times, t_ms) - 1)
                mm_mobs = minimap_frames[mmi]["mobs"]
            else:
                mm_mobs = []

            # Keyboard at tick rate — independent of (slow) render frame rate
            if act_times:
                ai         = max(0, bisect.bisect_right(act_times, t_ms) - 1)
                kbd_action = action_frames[ai]["action"]
            else:
                kbd_action = frames[fi].get("action", " ")

            f = frames[fi]

            img = _render_one_frame(
                f["frame"], kbd_action, f["render_ms"], f.get("tick_ms"),
                mm_mobs, map_cache, map_bounds,
                ascii_h, ch, bottom_h, img_w,
                font_ascii, font_key, font_fire, font_sub, font_metric,
                db_name=db_name, game_w_natural=game_w_natural,
                font_dbname=font_dbname, redact_metrics=redact_metrics,
                fps_series=fps_series, tick_series=tick_series,
                t_ms=t_ms, total_ms=total_ms,
            )

            img.save(os.path.join(tmpdir, f"frame_{slot:06d}.png"))
            if slot % 30 == 0:
                sys.stdout.write(f"\r  [video] encoding {slot}/{n_slots} frames…  ")
                sys.stdout.flush()

        print()
        result = subprocess.run([
            "ffmpeg", "-y",
            "-framerate", str(TARGET_FPS),
            "-i", os.path.join(tmpdir, "frame_%06d.png"),
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-preset", "fast", "-crf", "18", "-tune", "animation",
            str(output_path),
        ], capture_output=True)
        if result.returncode != 0:
            err = result.stderr.decode(errors="replace")
            lines = [l for l in err.splitlines() if l.strip()]
            print("  [video error]", "\n    ".join(lines[-6:]))
            return False

    return True
