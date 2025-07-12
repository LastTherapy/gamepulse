#!/usr/bin/env python3
# bot_with_viewer.py — вывод JSON-ответа прямо в окне

import threading, time, heapq, random, sys, json, requests, pygame
from collections import defaultdict
from datspulse_viewer import ArenaRenderer

# ───────── API / параметры ────────────────────────────────────────────────
URL   = "https://games-test.datsteam.dev"
TOKEN = "39413815-04e3-4ba6-b21e-ad5c29ca2cee"
H     = {"accept": "application/json", "X-Auth-Token": TOKEN}

TICK_SEC   = 2.0        # период хода, чтобы не спамить сервер
ACID_PEN   = 5          # штраф за кислоту
SCOUT_STEP = 4          # шаг сетки «разведчиков»

# ───────── глобальный статус для вывода -----------------------------------
status_text = "‣ waiting registration…"

# ───────── геометрия / A* --------------------------------------------------
DIRS = [(+1, 0), (+1, -1), (0, -1), (-1, 0), (-1, +1)]

def hex_dist(a, b):
    aq, ar = a
    bq, br = b
    return max(abs(aq - bq),
               abs(ar - br),
               abs((aq + ar) - (bq + br)))

def a_star(start, goal, move_cost, penalty):
    """Обычный A* по гексагонам (без диагоналей)."""
    if move_cost.get(goal) is None:
        return None

    pq = [(hex_dist(start, goal), 0, start)]
    best = {start: 0}
    came = {}

    while pq:
        pq.sort(key=lambda x: x[0])          # маленькая очередь — сортировка дешевле
        f, g, cur = pq.pop(0)
        if cur == goal:                      # найдено
            path = [cur]
            while cur in came:
                cur = came[cur]
                path.append(cur)
            return path[::-1]

        for dq, dr in DIRS:
            nxt = (cur[0] + dq, cur[1] + dr)
            mc  = move_cost.get(nxt)
            if mc is None:                              # стена / нечего делать
                continue
            g2 = g + mc + penalty.get(nxt, 0)
            if g2 < best.get(nxt, 1e9):
                best[nxt] = g2
                came[nxt] = cur
                heapq.heappush(pq, (g2 + hex_dist(nxt, goal), g2, nxt))
    return None

# ───────── регистрация ----------------------------------------------------
def wait_register():
    global status_text
    deadline = time.time() + 5 * 60
    while time.time() < deadline:
        r = requests.post(URL + "/api/register", headers=H)
        if r.status_code == 200:
            status_text = "✓ registered, waiting start…"
            return True
        status_text = f"register {r.status_code}: {r.text.strip()}"
        time.sleep(5)
    status_text = "⨯ registration window closed"
    return False

# ───────── бот-поток -------------------------------------------------------
def bot(renderer: ArenaRenderer):
    global status_text
    if not wait_register():
        sys.exit(1)

    known       = {}                   # карта клеток
    mem_path    = defaultdict(list)    # «память» маршрутов
    scout_grid  = []                   # заранее размечённая сетка
    last_move_t = 0.0                  # чтобы не спамить

    while True:
        arena = requests.get(URL + "/api/arena", headers=H).json()
        renderer.set_state(arena)

        # до старта показываем сырой JSON
        if not arena.get("map"):
            status_text = json.dumps(arena, indent=2, ensure_ascii=False)
            time.sleep(2)
            continue

        # краткая сводка
        status_text = (f"turn {arena['turnNo']}  "
                       f"ants:{len(arena['ants'])}  "
                       f"food:{len(arena['food'])}")

        # обновляем карту
        for c in arena["map"]:
            known[(c["q"], c["r"])] = c["type"]

        # задаём стоимости перемещения
        move_cost = {(q, r): (2 if t == 3 else 1) if t != 5 else None
                     for (q, r), t in known.items()}
        penalty   = {(q, r): ACID_PEN if t == 4 else 0
                     for (q, r), t in known.items()}

        # вспомогательные списки
        spot     = (arena["spot"]["q"], arena["spot"]["r"])
        helpers  = [(h["q"], h["r"]) for h in arena["home"] if (h["q"], h["r"]) != spot]
        food_set = [(f["q"], f["r"]) for f in arena["food"]]

        # сетка точек для разведчиков строится один раз
        if not scout_grid:
            rng = range(-SCOUT_STEP * 4, SCOUT_STEP * 4 + 1)
            for dq in rng:
                for dr in rng:
                    if dq % SCOUT_STEP == dr % SCOUT_STEP == 0:
                        cell = (spot[0] + dq, spot[1] + dr)
                        if known.get(cell, 5) != 5:      # не чёрная дыра
                            scout_grid.append(cell)

        # соблюдаем TICK_SEC
        if time.time() - last_move_t < TICK_SEC:
            time.sleep(0.2)
            continue
        last_move_t = time.time()

        occupied     = {(a["q"], a["r"]) for a in arena["ants"]}
        used_targets = set()            # цели, которые уже выбраны в этом ходу
        moves        = []

        # ------------- главный цикл по муравьям ---------------------------
        for ant in arena["ants"]:
            aid  = ant["id"]
            typ  = ant["type"]
            pos  = (ant["q"], ant["r"])
            has_food = ant["food"]["amount"] > 0

            # гарантируем, что есть список в памяти
            path = mem_path[aid]

            # сброс, если шаг конфликтует
            def path_conflicts(p):
                return (not p or
                        p[0] in occupied or
                        p[0] in used_targets)

            attempt = 0
            while attempt < 3 and path_conflicts(path):
                # ищем цель
                if typ == 2:                        # разведчик
                    if scout_grid:
                        target = min(scout_grid, key=lambda c: hex_dist(pos, c))
                    else:                           # если сетка пуста
                        dq, dr = random.choice(DIRS)
                        target = (pos[0] + dq, pos[1] + dr)
                elif has_food:
                    target = min(helpers, key=lambda h: hex_dist(pos, h))
                elif food_set:
                    target = min(food_set, key=lambda f: hex_dist(pos, f))
                else:
                    dq, dr = random.choice(DIRS)
                    target = (pos[0] + dq, pos[1] + dr)

                new_path = a_star(pos, target, move_cost, penalty)
                if not new_path:                    # A* не нашёл путь
                    break
                mem_path[aid] = path = new_path[1:]  # без текущей клетки
                attempt += 1

            # если после всех попыток конфликт — остаёмся
            if path_conflicts(path):
                step = pos
            else:
                step = path.pop(0)                  # реальный ход
                used_targets.add(step)              # резервируем клетку

            moves.append({"ant": aid,
                          "path": [{"q": step[0], "r": step[1]}]})

        # отправляем ходы
        requests.post(URL + "/api/move", headers=H, json={"moves": moves})

# ───────── главное окно ----------------------------------------------------
def main():
    global status_text
    pygame.init()
    screen = pygame.display.set_mode((1280, 800), pygame.RESIZABLE)
    pygame.display.set_caption("Datspulse bot – live JSON on screen")
    renderer = ArenaRenderer(screen)
    font = pygame.font.SysFont("consolas", 14)

    threading.Thread(target=bot, args=(renderer,), daemon=True).start()

    clock = pygame.time.Clock()
    running = True
    while running:
        for e in pygame.event.get():
            if e.type == pygame.QUIT or (e.type == pygame.KEYDOWN and e.key == pygame.K_ESCAPE):
                running = False
            renderer.handle_event(e)

        renderer.draw()

        # текст поверх
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
