#!/usr/bin/env python3
import importlib, json, re, sys, time, threading
from pathlib import Path

from video import frames_to_video

# ── Configuration ─────────────────────────────────────────────────────────────
DURATION             = 60      # seconds per benchmark
VIEWERS              = (1, 2, 3, 4)
SHOW_EVERY           = 1.0     # seconds between live previews
HTAP_TICK_HZ         = 35      # target tick rate during HTAP benchmark
REPLAY_DURATION      = 10      # seconds for scripted combat replay
REPLAY_TICK_HZ       = 30      # fixed server tick rate during replay

# Adapter names whose benchmark numbers cannot be published (DeWitt clause).
# Videos are fine; metric values in the METRICS panel are redacted.
DEWITT_REDACTED      = {"alloydb"}

# Per-tick input cycle (300 ticks = 10s x 30Hz).
# Phase 1 - spin (64 ticks, 2.1s): 'a' every other tick = half-speed rotation.
#   32 actual turns x 0.2 rad = 6.4 rad ~= full circle.
#   SQL snaps to dir=0 at tick 64 before first stride.
# Phase 2 - walk+shoot (120 ticks, 4s): stride east through corridor, kill P2.
#   P2 walked to x~17.5 (mid-corridor) and is waiting. P2 teleports on kill.
# Phase 3 - walk deeper (30 ticks, 1s): into Room B.
# Phase 4 - turn (16 ticks, 0.5s): 'd' right-turns ~180deg.
#   SQL snaps to dir=pi at tick 230 before walk-back.
# Phase 5 - walk back (70 ticks, 2.3s): 21 tiles west -> back through corridor.
#
# Both direction snaps done via SQL UPDATE (immune to turn_speed variance).
_P1_STRIDE       = ['w'] * 11 + ['x'] * 4         # 15-tick walk-and-shoot stride
_P1_SPIN         = ['a', ' '] * 32                 # half-speed: 64 ticks for full circle
SPIN_SNAP        = len(_P1_SPIN)                   # = 64: snap to dir=0 after spin
TURN_PHASE_START = SPIN_SNAP + 120 + 30 + 16      # = 230: snap to dir=pi for walk-back
REPLAY_INPUT_CYCLE = (
    _P1_SPIN +          # 64 ticks: slow full-circle spin
    _P1_STRIDE * 8 +    # 120 ticks: walk east, shoot P2 in corridor
    ['w'] * 30 +        # 30 ticks: walk deeper into Room B
    ['d'] * 16 +        # 16 ticks: gradual ~180deg right-turn
    ['w'] * 70          # 70 ticks: walk back through corridor
)  # 300 ticks total

# ── Helpers ───────────────────────────────────────────────────────────────────
def read_sql(adapter, name):
    return Path(adapter.sql_path(name)).read_text(encoding="utf8")

def _split_statements(sql):
    """Split a SQL string into individual statements, stripping comments."""
    no_comments = re.sub(r"--[^\n]*", "", sql)
    return [s.strip() for s in no_comments.split(";") if s.strip()]

_frame_lines = 0  # lines occupied by the last displayed frame

def _display_frame(rows, header=""):
    global _frame_lines
    if _frame_lines:
        sys.stdout.write(f"\033[{_frame_lines}A\033[J")
    if header:
        sys.stdout.write(header + "\n\n")
    for (full_row,) in rows:
        sys.stdout.write(full_row + "\n")
    sys.stdout.write("\n")
    sys.stdout.flush()
    _frame_lines = (2 if header else 0) + len(rows) + 1

def _pct(lst, p):
    if not lst: return None
    return lst[max(0, min(int(p * len(lst)), len(lst) - 1))]

def _fresh_start(adapter, player_seed="seeds/static_players.sql"):
    """Restart the container for a guaranteed clean database, then prepare and seed."""
    global _frame_lines
    _frame_lines = 0
    adapter.stop()
    adapter.start()
    adapter.wait_ready()
    prepare(adapter)
    conn, cur = adapter.new_connection()
    for fname in ("seeds/complex_map.sql", player_seed):
        sql = re.sub(r"--[^\n]*", "", read_sql(adapter, fname))
        for stmt in (s.strip() for s in sql.split(";")):
            if stmt:
                cur.execute(stmt)
    try:
        cur.execute(
            "INSERT INTO inputs(player_id, action) "
            "SELECT id, 'w' FROM players "
            "ON CONFLICT (player_id) DO NOTHING"
        )
    except Exception:
        pass
    conn.close()
    adapter.after_prepare()

def bench_fps(adapter):
    """Pure OLAP: each viewer renders their own player's perspective, world is static.

    Players are seeded across distinct map rooms so each concurrent query
    exercises a meaningfully different view frustum. That's the same workload a
    real game server would produce when serving N simultaneous clients.
    """
    _fresh_start(adapter)

    render_sql = "SELECT full_row FROM screen WHERE player_id = %s ORDER BY y"
    latencies, frames = [], 0
    last_screens  = {}  # player_id → most recent rendered rows (for cycling display)
    preview_cycle = 0
    fatal = []
    lock = threading.Lock()
    start = time.time()
    stop_at = start + DURATION
    next_show = start + SHOW_EVERY

    def worker(player_id):
        nonlocal frames, next_show, preview_cycle
        conn, cur = adapter.new_olap_connection()
        try:
            while time.time() < stop_at:
                t0 = time.perf_counter()
                cur.execute(render_sql, (player_id,))
                screen = cur.fetchall()
                elapsed_q = time.perf_counter() - t0
                with lock:
                    last_screens[player_id] = screen
                    latencies.append(elapsed_q)
                    frames += 1
                    now = time.time()
                    if now >= next_show:
                        next_show = now + SHOW_EVERY
                        show_pid = VIEWERS[preview_cycle % len(VIEWERS)]
                        preview_cycle += 1
                        snap = sorted(latencies)
                        fps_cur = frames / (now - start)
                        p50_cur = (_pct(snap, 0.50) or 0) * 1000
                        p99_cur = (_pct(snap, 0.99) or 0) * 1000
                        hdr = (f"── [1/4] FPS  "
                               f"{now-start:.0f}s/{DURATION}s  "
                               f"fps={fps_cur:.1f}  "
                               f"p50={p50_cur:.0f}ms  p99={p99_cur:.0f}ms  "
                               f"[viewer {show_pid}]")
                        try:
                            _display_frame(last_screens.get(show_pid, screen), header=hdr)
                        except Exception:
                            pass
        except Exception as e:
            with lock:
                fatal.append(e)
        finally:
            conn.close()

    threads = [threading.Thread(target=worker, args=(pid,), daemon=True)
               for pid in VIEWERS]
    for t in threads: t.start()
    for t in threads: t.join()
    if fatal:
        raise fatal[0]

    elapsed = time.time() - start
    latencies.sort()
    fps = frames / elapsed
    p50 = _pct(latencies, 0.50)
    p95 = _pct(latencies, 0.95)
    p99 = _pct(latencies, 0.99)

    return {
        "fps_static":        round(fps, 1),
        "fps_static_p50_ms": round(p50 * 1000, 2) if p50 else None,
        "fps_static_p95_ms": round(p95 * 1000, 2) if p95 else None,
        "fps_static_p99_ms": round(p99 * 1000, 2) if p99 else None,
    }

def bench_ticks(adapter):
    """Pure OLTP: run game ticks at max speed, no concurrent rendering.
    Players respawn at their seeded positions so the fight resets on every kill."""
    _fresh_start(adapter)
    tick_stmts = _split_statements(read_sql(adapter, "tick.sql"))

    count = 0
    start = time.time()
    stop_at = start + DURATION
    next_print = start + SHOW_EVERY

    conn, cur = adapter.new_connection()
    while time.time() < stop_at:
        try:
            cur.execute("UPDATE inputs SET action = 'x'")
        except Exception:
            pass
        for stmt in tick_stmts:
            cur.execute(stmt)
        count += 1
        now = time.time()
        if now >= next_print:
            elapsed = now - start
            rate = count / elapsed if elapsed > 0 else 0
            print(f"\r── [2/4] TICK RATE  {elapsed:.0f}s/{DURATION}s  "
                  f"ticks={count}  rate={rate:.0f}/s",
                  end="", flush=True)
            next_print = now + SHOW_EVERY
    conn.close()

    print()  # newline after the final \r update
    return {"ticks_per_sec": round(count / DURATION, 1)}

def bench_latency(adapter):
    """True pipeline latency across three separate connections:
    writer commits the input, ticker commits the tick, reader verifies the
    state actually changed. Runs for DURATION seconds. """
    _fresh_start(adapter)
    tick_stmts = _split_statements(read_sql(adapter, "tick.sql"))
    render_sql = "SELECT full_row FROM screen WHERE player_id = %s ORDER BY y"

    conn_w, cur_w = adapter.new_connection()        # commits inputs
    conn_t, cur_t = adapter.new_connection()        # runs tick transactions
    conn_r, cur_r = adapter.new_olap_connection()   # reads / verifies state

    POLL_LIMIT = 20   # max tick+render retries before declaring a timeout

    lats, timeouts = [], 0
    start     = time.time()
    stop_at   = start + DURATION
    next_show = start + SHOW_EVERY

    # Seed baseline screen before the first timed sample
    cur_r.execute(render_sql, (1,))
    screen_before = cur_r.fetchall()
    screen = screen_before

    while time.time() < stop_at:
        # Write the input, clock starts here
        t0 = time.perf_counter()
        try:
            # 'a' (turn left) always changes the rendered frame regardless of walls.
            cur_w.execute("UPDATE inputs SET action = 'a' WHERE player_id = 1")
        except Exception:
            pass

        # Keep ticking and rendering until the screen changes or we give up
        visible = False
        for _ in range(POLL_LIMIT):
            for stmt in tick_stmts:
                cur_t.execute(stmt)
            cur_r.execute(render_sql, (1,))
            screen = cur_r.fetchall()
            if screen != screen_before:
                lats.append(time.perf_counter() - t0)
                visible = True
                break

        if not visible:
            timeouts += 1

        screen_before = screen

        now = time.time()
        if now >= next_show:
            next_show = now + SHOW_EVERY
            elapsed   = now - start
            n         = len(lats)
            p50_cur   = (_pct(sorted(lats), 0.50) or 0) * 1000
            hdr = (f"── [3/4] INPUT LAG  "
                   f"{elapsed:.0f}s/{DURATION}s  "
                   f"n={n}  p50={p50_cur:.1f}ms  timeouts={timeouts}")
            _display_frame(screen, header=hdr)

    conn_w.close()
    conn_t.close()
    conn_r.close()

    n = len(lats)
    lats.sort()
    p50 = _pct(lats, 0.50)
    p95 = _pct(lats, 0.95) if n >= 20  else None
    p99 = _pct(lats, 0.99) if n >= 100 else None
    return {
        "latency_p50_ms":  round(p50 * 1000, 2) if p50 else None,
        "latency_p95_ms":  round(p95 * 1000, 2) if p95 else None,
        "latency_p99_ms":  round(p99 * 1000, 2) if p99 else None,
        "latency_samples":  n,
        "latency_timeouts": timeouts,
    }

def bench_htap(adapter):
    """Mixed load: tick thread at HTAP_TICK_HZ + 4 concurrent render viewers."""
    _fresh_start(adapter)
    tick_stmts = _split_statements(read_sql(adapter, "tick.sql"))
    render_sql = "SELECT full_row FROM screen WHERE player_id = %s ORDER BY y"

    latencies, frames = [], 0
    ticks_attempted = ticks_on_time = 0
    fatal = []
    lock = threading.Lock()
    stop_event = threading.Event()
    start = time.time()
    stop_at = start + DURATION
    next_show = start + SHOW_EVERY

    def tick_worker():
        nonlocal ticks_attempted, ticks_on_time
        conn, cur = adapter.new_connection()
        interval = 1.0 / HTAP_TICK_HZ
        next_tick = time.time() + interval
        while not stop_event.is_set():
            sleep_for = next_tick - time.time()
            if sleep_for > 0:
                time.sleep(sleep_for)
            t0 = time.perf_counter()
            try:
                cur.execute("UPDATE inputs SET action = 'x'")
                for stmt in tick_stmts:
                    cur.execute(stmt)
            except Exception:
                pass
            elapsed = time.perf_counter() - t0
            with lock:
                ticks_attempted += 1
                if elapsed < interval:
                    ticks_on_time += 1
            next_tick += interval
        conn.close()

    def render_worker(idx):
        nonlocal frames, next_show
        conn, cur = adapter.new_olap_connection()
        try:
            while time.time() < stop_at:
                t0 = time.perf_counter()
                try:
                    cur.execute(render_sql, (idx,))
                    screen = cur.fetchall()
                except Exception as e:
                    if "out of memory" in str(e).lower():
                        raise
                    screen = None
                with lock:
                    latencies.append(time.perf_counter() - t0)
                    frames += 1
                    now = time.time()
                    if idx == VIEWERS[0] and screen and now >= next_show:
                        next_show = now + SHOW_EVERY
                        snap = sorted(latencies)
                        fps_cur = frames / (now - start)
                        p99_cur = (_pct(snap, 0.99) or 0) * 1000
                        on_time = (100.0 * ticks_on_time / ticks_attempted
                                   if ticks_attempted else 0)
                        hdr = (f"── [4/4] HTAP  "
                               f"{now-start:.0f}s/{DURATION}s  "
                               f"fps={fps_cur:.1f}  p99={p99_cur:.0f}ms  "
                               f"ticks_on_time={on_time:.0f}%  "
                               f"(reads + writes simultaneously)")
                        try:
                            _display_frame(screen, header=hdr)
                        except Exception:
                            pass
        except Exception as e:
            with lock:
                fatal.append(e)
        finally:
            conn.close()

    tick_t = threading.Thread(target=tick_worker, daemon=True)
    render_ts = [threading.Thread(target=render_worker, args=(i,), daemon=True)
                 for i in VIEWERS]

    tick_t.start()
    for t in render_ts: t.start()
    for t in render_ts: t.join()
    stop_event.set()
    tick_t.join(timeout=3)
    if fatal:
        raise fatal[0]

    elapsed = time.time() - start
    latencies.sort()
    fps = frames / elapsed
    tps = ticks_attempted / elapsed
    p50 = _pct(latencies, 0.50)
    p99 = _pct(latencies, 0.99)
    on_time = round(100.0 * ticks_on_time / ticks_attempted, 1) if ticks_attempted else None
    doom_score = round(fps * min(1.0, tps / HTAP_TICK_HZ), 1)

    return {
        "doom_score":        doom_score,
        "fps_htap":          round(fps, 1),
        "tps_htap":          round(tps, 1),
        "fps_htap_p50_ms":   round(p50 * 1000, 2) if p50 else None,
        "fps_htap_p99_ms":   round(p99 * 1000, 2) if p99 else None,
        "ticks_on_time_pct": on_time,
    }

def bench_replay(adapter):
    """Fixed-rate server tick thread + two independent render threads.

    Three connections run concurrently:
      conn_t: tick + input writes (OLTP)
      conn_r: raycaster screen query (OLAP, slow)
      conn_m: minimap mob-position query (OLTP, fast)

    The minimap connection captures server state at near-tick rate even on slow
    DBs, while the game view might lag behind."""
    _fresh_start(adapter, "seeds/replay_players.sql")

    tick_stmts  = _split_statements(read_sql(adapter, "tick.sql"))
    render_sql  = "SELECT full_row FROM screen WHERE player_id = %s ORDER BY y"
    minimap_sql = "SELECT x, y, minimap_icon, dir FROM mobs WHERE minimap_icon IS NOT NULL"

    # Short looping cycle so P2 visibly walks toward P1 after every respawn.
    # Respawn restores P2 to spawn position (facing west toward P1), so each
    # new cycle shows P2 approaching from the east end of the corridor again.
    P2_INPUT_CYCLE = [' '] * 65 + ['w'] * 15 + ['x'] * 2  # wait through P1 spin, then approach

    conn_t, cur_t = adapter.new_connection()        # tick + inputs
    conn_r, cur_r = adapter.new_olap_connection()   # raycaster render (slow OLAP)
    conn_m, cur_m = adapter.new_olap_connection()   # minimap mob positions

    # Cache static map tiles once — they never change during the replay
    cur_m.execute("SELECT x, y, tile FROM map ORDER BY y, x")
    map_cache = cur_m.fetchall()
    if map_cache:
        xs = [r[0] for r in map_cache]; ys = [r[1] for r in map_cache]
        map_bounds = (min(xs), max(xs), min(ys), max(ys))
    else:
        map_bounds = (0, 20, 0, 20)

    frames          = []
    minimap_frames  = []   # independent timeline — updated faster than game frames
    action_frames   = []   # per-tick action timeline — animates keyboard at tick rate
    mm_lock         = threading.Lock()
    stop_event      = threading.Event()
    last_tick_ms    = [None]
    last_action     = [" "]
    tick_ms_lock    = threading.Lock()

    # Define start before launching threads so closures see a valid value
    start = time.time()
    snapped_east = False   # one-shot: snap P1 to dir=0 after spin ends
    snapped_west = False   # one-shot: snap P1 to dir=π for turnaround

    def tick_worker():
        nonlocal snapped_east, snapped_west
        interval   = 1.0 / REPLAY_TICK_HZ
        next_tick  = time.time() + interval
        tick_count = 0
        while not stop_event.is_set():
            sleep_for = next_tick - time.time()
            if sleep_for > 0:
                time.sleep(sleep_for)
            # Use tick_count (not wall-clock) so slow DBs replay the same input sequence,
            action    = REPLAY_INPUT_CYCLE[tick_count % len(REPLAY_INPUT_CYCLE)]
            p2_action = P2_INPUT_CYCLE[tick_count % len(P2_INPUT_CYCLE)]
            # After spin: snap dir to exactly 0 (east) so P1 walks straight through corridor.
            if tick_count >= SPIN_SNAP and not snapped_east:
                snapped_east = True
                try:
                    cur_t.execute("UPDATE mobs SET dir = 0 WHERE id = 1")
                except Exception:
                    pass
            # Turnaround: snap dir to exactly π (west) — immune to turn_speed accumulation.
            if tick_count >= TURN_PHASE_START and not snapped_west:
                snapped_west = True
                try:
                    cur_t.execute("UPDATE mobs SET dir = 3.14159265358979 WHERE id = 1")
                except Exception:
                    pass
            try:
                cur_t.execute("UPDATE inputs SET action = %s WHERE player_id = 1", (action,))
                cur_t.execute("UPDATE inputs SET action = %s WHERE player_id = 2", (p2_action,))
                t0 = time.perf_counter()
                for stmt in tick_stmts:
                    cur_t.execute(stmt)
                ms = round((time.perf_counter() - t0) * 1000, 1)
                with tick_ms_lock:
                    last_tick_ms[0] = ms
                    last_action[0]  = action
                action_frames.append({
                    "t":      round((time.time() - start) * 1000),
                    "action": action,
                })
            except Exception as e:
                print(f"\n  [R] tick error: {e}", flush=True)
            tick_count += 1
            next_tick  += interval

    def minimap_worker():
        # Cap at tick rate — mob positions only change once per tick, no point polling faster.
        interval  = 1.0 / REPLAY_TICK_HZ
        next_poll = time.time() + interval
        while not stop_event.is_set():
            sleep_for = next_poll - time.time()
            if sleep_for > 0:
                time.sleep(sleep_for)
            try:
                t0   = time.perf_counter()
                cur_m.execute(minimap_sql)
                mobs = cur_m.fetchall()
                ms   = round((time.perf_counter() - t0) * 1000, 1)
                with mm_lock:
                    minimap_frames.append({
                            "t":    round((time.time() - start) * 1000),
                            "mobs": mobs,
                            "ms":   ms,
                        })
            except Exception:
                pass
            next_poll += interval

    tick_thread    = threading.Thread(target=tick_worker,    daemon=True)
    minimap_thread = threading.Thread(target=minimap_worker, daemon=True)
    tick_thread.start()
    minimap_thread.start()

    start = time.time()
    while time.time() - start < REPLAY_DURATION:
        t0 = time.perf_counter()
        try:
            cur_r.execute(render_sql, (1,))
            frame_rows = [r[0] for r in cur_r.fetchall()]
        except Exception as e:
            print(f"\n  [R] render error: {e}", flush=True)
            frame_rows = []
        render_ms = round((time.perf_counter() - t0) * 1000, 1)

        if frame_rows:
            with tick_ms_lock:
                tick_ms = last_tick_ms[0]
                action  = last_action[0]
            frames.append({
                "t":         round((time.time() - start) * 1000),
                "action":    action,
                "render_ms": render_ms,
                "tick_ms":   tick_ms,
                "frame":     frame_rows,
            })

        elapsed = time.time() - start
        sys.stdout.write(f"\r  [R] replay: {len(frames)} frames  {elapsed:.0f}s/{REPLAY_DURATION}s  ")
        sys.stdout.flush()

    stop_event.set()
    tick_thread.join(timeout=2)
    minimap_thread.join(timeout=2)
    for c in (conn_t, conn_r, conn_m):
        c.close()
    print()

    n = len(frames)
    avg_r = round(sum(f["render_ms"] for f in frames) / n, 1) if n else None
    return {
        "replay_frames":         frames,
        "replay_minimap_frames": minimap_frames,
        "replay_action_frames":  action_frames,
        "replay_map_cache":      map_cache,
        "replay_map_bounds":     map_bounds,
        "replay_total_frames":   n,
        "replay_avg_render_ms":  avg_r,
    }





# ── Setup ─────────────────────────────────────────────────────────────────────
def prepare(adapter):
    conn, cur = adapter.new_connection()
    adapter.exec_sql_file(cur, "schema.sql")
    adapter.exec_sql_file(cur, "sprites/player.sql")
    adapter.exec_sql_file(cur, "sprites/slug.sql")
    adapter.exec_sql_file(cur, "renderer.sql")
    conn.close()


# ── Per-adapter run ───────────────────────────────────────────────────────────
def run_one(adapter_modname):
    mod = importlib.import_module(f"adapters.{adapter_modname}")
    adapter = mod.Adapter()
    db_version = getattr(mod, 'IMAGE', getattr(mod, 'PG_IMAGE', None))
    print(f"\n=== {adapter.NAME} ===")
    try:
        print("  [1/4] FPS …")
        fps   = bench_fps(adapter)
        print(f"        fps_static={fps['fps_static']}")
        print("  [2/4] Ticks …")
        ticks = bench_ticks(adapter)
        print(f"        ticks_per_sec={ticks['ticks_per_sec']}")
        print("  [3/4] Latency …")
        lag   = bench_latency(adapter)
        print(f"        latency_p50_ms={lag['latency_p50_ms']}")
        print("  [4/4] HTAP …")
        htap  = bench_htap(adapter)
        print(f"        fps_htap={htap['fps_htap']}")
        print("  [R] Replay …")
        replay = bench_replay(adapter)
        print(f"        {replay.get('replay_total_frames', 0)} frames in {REPLAY_DURATION}s  avg_render={replay.get('replay_avg_render_ms')}ms")
        result = {"db": adapter.NAME, "db_version": db_version, **fps, **ticks, **lag, **htap, **replay}
        return result
    finally:
        adapter.stop()

RESULTS_DIR = Path("results")

def _save_replay_video(name, result):
    """Pop replay fields from result and render to MP4. Mutates result in place."""
    replay_frames  = result.pop("replay_frames",         None)
    minimap_frames = result.pop("replay_minimap_frames", None)
    action_frames  = result.pop("replay_action_frames",  None)
    map_cache      = result.pop("replay_map_cache",      None)
    map_bounds     = result.pop("replay_map_bounds",     None)
    if not replay_frames:
        return
    video_path = RESULTS_DIR / f"{name}_replay.mp4"
    if frames_to_video(replay_frames, video_path,
                       map_cache=map_cache, map_bounds=map_bounds,
                       minimap_frames=minimap_frames, action_frames=action_frames,
                       db_name=name,
                       redact_metrics=name.lower() in DEWITT_REDACTED):
        print(f"  → saved {video_path}")

def save_result(name, result):
    RESULTS_DIR.mkdir(exist_ok=True)
    _save_replay_video(name, result)
    path = RESULTS_DIR / f"{name}.json"
    path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf8")
    print(f"  → saved {path}")

# ── Replay-only run ───────────────────────────────────────────────────────────
def run_replay_only(adapter_modname):
    """Record a replay video without running benchmarks.
    Merges replay metadata into the existing results JSON if present."""
    mod     = importlib.import_module(f"adapters.{adapter_modname}")
    adapter = mod.Adapter()
    print(f"\n=== {adapter.NAME} (replay) ===")
    try:
        print("  [R] Replay …")
        replay = bench_replay(adapter)
        print(f"        {replay.get('replay_total_frames', 0)} frames in {REPLAY_DURATION}s"
              f"  avg_render={replay.get('replay_avg_render_ms')}ms")

        RESULTS_DIR.mkdir(exist_ok=True)
        _save_replay_video(adapter_modname, replay)

        # Merge replay metadata into existing JSON (if any)
        json_path = RESULTS_DIR / f"{adapter_modname}.json"
        if json_path.exists():
            existing = json.loads(json_path.read_text(encoding="utf8"))
            existing.update(replay)
            json_path.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf8")
            print(f"  → updated {json_path}")
    finally:
        adapter.stop()


# ── Entry point ───────────────────────────────────────────────────────────────
def _discover_adapters():
    """Return adapter names from all adapters/*.py files except base."""
    return sorted(
        p.stem for p in (Path(__file__).parent / "adapters").glob("*.py")
        if p.stem not in ("base", "__init__")
    )

if __name__ == "__main__":
    args = sys.argv[1:]
    replay_only = "--replay" in args
    if replay_only:
        args = [a for a in args if a != "--replay"]

    if not args:
        args = _discover_adapters()
        print(f"No adapters specified — running all {len(args)}: {', '.join(args)}")

    for name in args:
        try:
            if replay_only:
                run_replay_only(name)
            else:
                result = run_one(name)
                save_result(name, result)
        except Exception as e:
            print(f"ERROR running {name}: {e}", file=sys.stderr)
            import traceback; traceback.print_exc()
            sys.exit(1)

    import render
    render.main()
