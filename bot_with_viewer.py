#!/usr/bin/env python3
# bot_with_viewer.py – Datspulse Ant Arena client + он-лайн-визуализация

import threading, time, heapq, random, sys, json, requests, pygame
from collections import defaultdict
from datspulse_viewer import ArenaRenderer         # поставляется организаторами

# ────────── API & константы ────────────────────────────────────────────────
URL   = "https://games-test.datsteam.dev"
TOKEN = "39413815-04e3-4ba6-b21e-ad5c29ca2cee"
H     = {"accept": "application/json", "X-Auth-Token": TOKEN}

ACID_PEN     = 5                 # штраф за попадание в кислоту
SCOUT_STEP   = 4                 # “шаг сетки” для разведчиков
MAX_POLL_RPS = 1.4               # не быстрее ≈1.4 запроса/с
POLL_DELAY   = 1 / MAX_POLL_RPS

# ────────── глобальное состояние для HUD в окне ───────────────────────────
status_text = "‣ waiting registration…"

# ────────── геометрия гекса и A* ───────────────────────────────────────────
DIRS = [(+1,0),(+1,-1),(0,-1),(-1,0),(-1,+1),(0,+1)]

def hex_dist(a, b):
    aq, ar = a
    bq, br = b
    return max(abs(aq-bq), abs(ar-br), abs((aq+ar)-(bq+br)))

def a_star(start, goal, move_cost, penalty, blocked):
    """
    Непроходимые клетки:
        • все, где move_cost == None;
        • всё, что есть в `blocked` (муравьи текущего тика).
    """
    if goal in blocked or move_cost.get(goal) is None:
        return None

    open_q = [(hex_dist(start, goal), 0, start)]
    best   = {start: 0}
    came   = {}

    while open_q:
        open_q.sort(key=lambda x: x[0])          # маленькая очередь – можно sort
        _, g, cur = open_q.pop(0)

        if cur == goal:
            path = [cur]
            while cur in came:
                cur = came[cur]
                path.append(cur)
            return path[::-1]                    # от start к goal

        for dq, dr in DIRS:
            nxt = (cur[0]+dq, cur[1]+dr)
            if nxt in blocked:
                continue
            mv = move_cost.get(nxt)
            if mv is None:                       # стена/камень
                continue
            g2 = g + mv + penalty.get(nxt, 0)
            if g2 < best.get(nxt, 1e9):
                best[nxt] = g2
                came[nxt] = cur
                f = g2 + hex_dist(nxt, goal)
                heapq.heappush(open_q, (f, g2, nxt))
    return None                                  # пути нет

# ────────── регистрация (работает ≤ 5 мин после запуска арены) ─────────────
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
    status_text = "⨯ registration window closed"
    return False

# ────────── рабочий поток бота ─────────────────────────────────────────────
def bot(renderer: ArenaRenderer):
    global status_text
    if not wait_register():
        sys.exit(1)

    known        = {}                # {(q,r): terrain_type}
    scout_grid   = []                # точки для обхода разведчиком
    last_turn    = -1
    last_poll_ts = 0.0

    while True:
        # ---- ограничиваем частоту GET ----
        now = time.time()
        if now - last_poll_ts < POLL_DELAY:
            time.sleep(POLL_DELAY - (now - last_poll_ts))
        last_poll_ts = time.time()

        arena = requests.get(URL + "/api/arena", headers=H).json()
        turn  = arena.get("turnNo", -1)
        if turn == last_turn:
            continue                         # ход не сменился – ждём следующего
        last_turn = turn

        renderer.set_state(arena)            # обновляем визуализацию

        # ---- до старта показываем сырой JSON ----
        if not arena.get("map"):
            status_text = json.dumps(arena, indent=2, ensure_ascii=False)
            continue

        status_text = (f"turn {arena['turnNo']:>4}  "
                       f"ants:{len(arena['ants']):<3}  "
                       f"food:{len(arena['food'])}")

        # ---- карта / стоимости перемещения ----
        for c in arena["map"]:
            known[(c["q"], c["r"])] = c["type"]

        move_cost = {(q, r): (2 if t == 3 else 1) if t != 5 else None
                     for (q, r), t in known.items()}
        penalty   = {(q, r): ACID_PEN if t == 4 else 0
                     for (q, r), t in known.items()}

        spot     = (arena["spot"]["q"], arena["spot"]["r"])
        helpers  = [(h["q"], h["r"]) for h in arena["home"] if (h["q"], h["r"]) != spot]
        resources = [(f["q"], f["r"]) for f in arena["food"]]

        # ---- строим сетку точек для разведки один раз ----
        if not scout_grid:
            rng = range(-SCOUT_STEP*4, SCOUT_STEP*4 + 1)
            for dq in rng:
                for dr in rng:
                    if dq % SCOUT_STEP == 0 and dr % SCOUT_STEP == 0:
                        cell = (spot[0] + dq, spot[1] + dr)
                        if known.get(cell, 5) != 5:    # не камень
                            scout_grid.append(cell)

        occupied     = {(a["q"], a["r"]) for a in arena["ants"]}  # все клетки с муравьями
        reservation  = set()                                      # куда уже ПОШЛИ в этом ходе
        moves        = []

        # ---- планируем ход для каждого муравья ----
        for ant in arena["ants"]:
            aid    = ant["id"]
            pos    = (ant["q"], ant["r"])
            typ    = ant["type"]
            laden  = ant["food"]["amount"] > 0

            # — выбираем список приоритетных целей —
            if typ == 2:  # Scout
                targets = sorted(scout_grid, key=lambda c: hex_dist(pos, c))
            elif laden:   # Worker с ресурсом → домой
                targets = sorted(helpers, key=lambda h: hex_dist(pos, h))
            elif resources:  # Worker налегке → ближайший ресурс
                free_res = [r for r in resources if r not in occupied]
                targets  = sorted(free_res, key=lambda r: hex_dist(pos, r))
            else:            # Soldier или fallback
                targets = []

            if not targets:  # нет целей или все заняты – пробуем случайный соседний шаг
                dq, dr = random.choice(DIRS)
                targets = [(pos[0] + dq, pos[1] + dr)]

            # — ищем первую достижимую цель —
            step = pos
            for tgt in targets:
                path = a_star(pos, tgt, move_cost, penalty, occupied)
                if path and len(path) > 1:
                    cand = path[1]
                    if cand not in reservation:    # клетку ещё никто не занял
                        step = cand
                        break

            reservation.add(step)
            moves.append({"ant": aid, "path": [{"q": step[0], "r": step[1]}]})

        # ---- одно POST-сообщение на ход ----
        requests.post(URL + "/api/move", headers=H, json={"moves": moves})

# ────────── визуализация / главное окно ────────────────────────────────────
def main():
    global status_text
    pygame.init()
    screen = pygame.display.set_mode((1280, 800), pygame.RESIZABLE)
    pygame.display.set_caption("Datspulse bot – live JSON on screen")
    renderer = ArenaRenderer(screen)
    font     = pygame.font.SysFont("consolas", 14)

    threading.Thread(target=bot, args=(renderer,), daemon=True).start()

    clock   = pygame.time.Clock()
    running = True
    while running:
        for e in pygame.event.get():
            if e.type == pygame.QUIT or (e.type == pygame.KEYDOWN and e.key == pygame.K_ESCAPE):
                running = False
            renderer.handle_event(e)

        renderer.draw()

        # HUD с текущим статусом
        y = 10
        for line in status_text.splitlines():
            surf = font.render(line[:120], True, (255, 255, 0))
            screen.blit(surf, (10, y))
            y += 16

        pygame.display.flip()
        clock.tick(60)

    pygame.quit()

if __name__ == "__main__":
    main()
