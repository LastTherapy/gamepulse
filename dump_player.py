#!/usr/bin/env python3
# dump_player.py
# ─────────────────────────────────────────────────────────────────────────────
# Проигрыватель сохранённых дампов /api/arena.
#
# • Берёт JSON-файлы вида 00001.json, 00002.json … из указанной папки,
#   сортирует «по-человечески» и крутит по кругу.
# • Каждые --interval секунд передаёт очередной кадр в визуализатор
#   (ArenaRenderer) — тот сам умеет игнорировать пустые map[].
# • ЛКМ — перетаскивание карты; Esc / крестик окна — выход.
#
# Запуск:
#   python dump_player.py --dir saved_runs/run_01
#   python dump_player.py --dir . --interval 0.5 --fps 120
# ----------------------------------------------------------------------------

import time, json, pathlib, argparse, pygame, re
from datspulse_viewer import ArenaRenderer   # <-- файл с рендером

# ------------ утилита «человеческой» сортировки файлов ----------------------
def human_key(s: str):
    return [int(t) if t.isdigit() else t.lower()
            for t in re.split(r'(\d+)', s)]

def load_frames(folder: pathlib.Path):
    files = sorted(folder.glob("*.json"), key=lambda p: human_key(p.name))
    for f in files:
        try:
            yield json.loads(f.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[skip] {f.name}: {e}")

# ----------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="run_05", help="folder with 00001.json …")
    ap.add_argument("--interval", default=1.0, type=float,
                    help="seconds between frames")
    ap.add_argument("--fps", default=60, type=int, help="render FPS")
    ap.add_argument("--fullscreen", action="store_true")
    args = ap.parse_args()

    dump_dir = pathlib.Path(args.dir)
    if not dump_dir.exists():
        print(f"[error] no such directory: {dump_dir}")
        return

    frames = list(load_frames(dump_dir))
    if not frames:
        print("[error] no JSON files found"); return

    # ------------- Pygame init ----------------------------------------------
    pygame.init()
    flags = pygame.FULLSCREEN if args.fullscreen else pygame.RESIZABLE
    screen = (pygame.display.set_mode((0,0), flags) if args.fullscreen
              else pygame.display.set_mode((1280, 800), flags))
    pygame.display.set_caption("DatsPulse dump player — drag with LMB")

    renderer = ArenaRenderer(screen)
    idx = 0
    renderer.set_state(frames[idx])          # стартовый кадр
    last_switch = time.time()

    clock = pygame.time.Clock()
    running = True
    while running:
        # ---------- events --------------------------------------------------
        for e in pygame.event.get():
            if e.type == pygame.QUIT or (
               e.type == pygame.KEYDOWN and e.key == pygame.K_ESCAPE):
                running = False
            renderer.handle_event(e)          # drag-мышь

        # ---------- кадро-переключатель -------------------------------------
        if time.time() - last_switch >= args.interval:
            idx = (idx + 1) % len(frames)     # кольцевой просмотр
            renderer.set_state(frames[idx])
            last_switch = time.time()

        # ---------- draw ----------------------------------------------------
        renderer.draw()
        pygame.display.flip()
        clock.tick(args.fps)

    pygame.quit()

if __name__ == "__main__":
    main()
