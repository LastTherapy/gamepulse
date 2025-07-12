#!/usr/bin/env python3
# bot_with_viewer.py – Datspulse Ant-Arena client + viewer
#   v3: «решётка 4×4» для всех ролей

import threading, time, heapq, random, sys, json, requests, pygame
from collections import defaultdict
from datspulse_viewer import ArenaRenderer      # библиотека организаторов

# ───────── API / константы ────────────────────────────────────────────────
URL   = "https://games-test.datsteam.dev"
TOKEN = "39413815-04e3-4ba6-b21e-ad5c29ca2cee"
H     = {"accept": "application/json", "X-Auth-Token": TOKEN}

GRID_STEP      = 4          # шаг узлов решётки
ACID_PEN       = 5          # штраф за кислоту
MAX_RPS        = 1.5        # ограничимся ~1.5 запроса/с
STEP_DELAY     = 1 / MAX_RPS

status_text = "‣ waiting registration…"         # строка поверх окна

# ───────── геометрия / A* ─────────────────────────────────────────────────
DIRS = [(+1,0),(+1,-1),(0,-1),(-1,0),(-1,+1),(0,+1)]

def hex_dist(a, b):
    aq, ar = a
    bq, br = b
    return max(abs(aq-bq), abs(ar-br), abs((aq+ar)-(bq+br)))

def a_star(start, goal, move_cost, penalty, blocked):
    if goal in blocked or move_cost.get(goal) is None:
        return None
    open_q = [(hex_dist(start, goal), 0, start)]
    best   = {start: 0};  came = {}

    while open_q:
        open_q.sort(key=lambda x: x[0])
        _, g, cur = open_q.pop(0)

        if cur == goal:                       # reconstruct
            path = [cur]
            while cur in came:
                cur = came[cur]
                path.append(cur)
            return path[::-1]

        for dq, dr in DIRS:
            nxt = (cur[0]+dq, cur[1]+dr)
            if nxt in blocked:
                continue
            mv = move_cost.get(nxt)
            if mv is None:
                continue
            g2 = g + mv + penalty.get(nxt, 0)
            if g2 < best.get(nxt, 1e9):
                best[nxt] = g2;  came[nxt] = cur
                f = g2 + hex_dist(nxt, goal)
                heapq.heappush(open_q, (f, g2, nxt))
    return None

# ───────── регистрация ────────────────────────────────────────────────────
def wait_register():
    global status_text
    deadline = time.time() + 5*60
    while time.time() < deadline:
        r = requests.post(URL + "/api/register", headers=H)
        if r.status_code == 200:
            status_text = "✓ registered, waiting start…"
            return True
        status_text = f"register {r.status_code}: {r.text.strip()}"
        time.sleep(5)
    status_text = "⨯ registration window closed";  return False

# ───────── генерация узлов решётки «4×4» вокруг spot ──────────────────────
def grid_layer(spot, radius):
    """hex’ы, у которых max(|dx|,|dy|)==radius • dx,dy кратны GRID_STEP"""
    sx, sy = spot
    for dq in range(-radius, radius+1):
        for dr in range(-radius, radius+1):
            if max(abs(dq), abs(dr)) != radius:
                continue
            yield (sx + dq*GRID_STEP,
                   sy + dr*GRID_STEP)

# ───────── основной поток-бот ─────────────────────────────────────────────
def bot(renderer: ArenaRenderer):
    global status_text
    if not wait_register():
        sys.exit(1)

    known         = {}                        # {(q,r): terrain_type}
    mem_goal      = {}                        # {ant_id: (q,r)}
    last_turn     = -1
    last_request  = 0.0

    grid_cache    = []                        # готовые узлы решётки
    next_radius   = 0                         # какой слой добавить далее

    while True:
        # ---- RPS-ограничитель ----
        now = time.time()
        if now - last_request < STEP_DELAY:
            time.sleep(STEP_DELAY - (now - last_request))
        last_request = time.time()

        arena = requests.get(URL + "/api/arena", headers=H).json()
        renderer.set_state(arena)

        turn = arena.get("turnNo", -1)
        if turn == last_turn:
            continue
        last_turn = turn

        status_text = (f"turn {turn:>4}  "
                       f"A:{len(arena['ants'])}  "
                       f"F:{len(arena['food'])}")

        # ---- карта / стоимости ----
        for c in arena["map"]:
            known[(c["q"], c["r"])] = c["type"]

        move_cost = {(q, r): (2 if t == 3 else 1) if t != 5 else None
                     for (q, r), t in known.items()}
        penalty   = {(q, r): ACID_PEN if t == 4 else 0
                     for (q, r), t in known.items()}

        spot      = (arena["spot"]["q"], arena["spot"]["r"])
        helpers   = [(h["q"], h["r"]) for h in arena["home"] if (h["q"], h["r"]) != spot]
        resources = [(f["q"], f["r"]) for f in arena["food"]]

        # ---- расширяем кэш узлов, если нужно ----
        while len(grid_cache) < len(arena["ants"]) * 2:   # с запасом
            next_radius += 1
            layer = [cell for cell in grid_layer(spot, next_radius)
                     if known.get(cell, 5) != 5]          # без камня
            grid_cache.extend(layer)

        occupied   = {(a["q"], a["r"]) for a in arena["ants"]}
        reserved   = set()
        targeted_res  = set()         # чтобы один ресурс — один Worker
        targeted_grid = set()         # чтобы узлы не дублировались

        # помним существующие цели-узлы, чтобы не выдавать их другим
        for a in arena["ants"]:
            tgt = mem_goal.get(a["id"])
            if tgt and tgt not in resources:
                targeted_grid.add(tgt)

        moves = []

        for ant in arena["ants"]:
            aid   = ant["id"]
            pos   = (ant["q"], ant["r"])
            typ   = ant["type"]
            laden = ant["food"]["amount"] > 0

            # ─── тип 1: Worker ────────────────────────────────────────────
            if typ == 1:
                if laden:                              # домой
                    goal = min(helpers, key=lambda h: hex_dist(pos, h))
                else:
                    # ресурс, который ещё никто не взял
                    free_res = [r for r in resources
                                if r not in targeted_res and r not in occupied]
                    if free_res:
                        goal = min(free_res, key=lambda r: hex_dist(pos, r))
                        targeted_res.add(goal)
                    else:                              # расползание
                        goal = mem_goal.get(aid)
                        if (goal in occupied or goal in targeted_grid or
                            goal is None or hex_dist(pos, goal) == 0):
                            # выдаём следующий свободный узел
                            for g in grid_cache:
                                if g not in occupied and g not in targeted_grid:
                                    goal = g;  break
                        targeted_grid.add(goal)

            # ─── Scouts (2) & Soldiers (3) ────────────────────────────────
            else:
                goal = mem_goal.get(aid)
                need_new = (goal is None or hex_dist(pos, goal) == 0 or
                             goal in occupied or goal in targeted_grid)
                if need_new:
                    for g in grid_cache:
                        if g not in occupied and g not in targeted_grid:
                            goal = g; break
                targeted_grid.add(goal)

            # ─── путь / шаг ───────────────────────────────────────────────
            blocked = (occupied | reserved) - {pos}
            path = a_star(pos, goal, move_cost, penalty, blocked)

            step = pos if not path or len(path) == 1 else path[1]
            reserved.add(step)
            mem_goal[aid] = goal

            moves.append({"ant": aid,
                          "path": [{"q": step[0], "r": step[1]}]})

        # ---- единый POST на ход ----
        requests.post(URL + "/api/move", headers=H, json={"moves": moves})

# ───────── визуализация ────────────────────────────────────────────────────
def main():
    global status_text
    pygame.init()
    screen   = pygame.display.set_mode((1280, 800), pygame.RESIZABLE)
    pygame.display.set_caption("Datspulse bot — live JSON on screen")
    renderer = ArenaRenderer(screen)
    font     = pygame.font.SysFont("consolas", 14)

    threading.Thread(target=bot, args=(renderer,), daemon=True).start()

    clock = pygame.time.Clock();  running = True
    while running:
        for e in pygame.event.get():
            if e.type == pygame.QUIT or (e.type == pygame.KEYDOWN and e.key == pygame.K_ESCAPE):
                running = False
            renderer.handle_event(e)

        renderer.draw()

        y = 10
        for line in status_text.splitlines():
            screen.blit(font.render(line, True, (255,255,0)), (10, y));  y += 16

        pygame.display.flip();  clock.tick(60)

    pygame.quit()

if __name__ == "__main__":
    main()
