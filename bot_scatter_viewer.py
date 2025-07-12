#!/usr/bin/env python3
"""Datspulse bot with built-in viewer.

Workers scatter around the map in search of food, picking it up when
found and returning it to the anthill. Movement is simultaneous and
collision-free: ants reserve their next cells so that paths do not
intersect and no two workers pursue the same resource or patrol node.
"""

import threading
import time
import heapq
import requests
import pygame
import random
import sys
from datspulse_viewer import ArenaRenderer

# ──────── API constants ───────────────────────────────────────────────────
URL = "https://games-test.datsteam.dev"
TOKEN = "39413815-04e3-4ba6-b21e-ad5c29ca2cee"
HEADERS = {"accept": "application/json", "X-Auth-Token": TOKEN}

GRID_STEP = 4
ACID_PENALTY = 5
MAX_RPS = 1.5
STEP_DELAY = 1 / MAX_RPS

status_text = "‣ waiting registration…"

# ──────── geometry / A* ─────────────────────────────────────────────────--
DIRS = [(+1,0),(+1,-1),(0,-1),(-1,0),(-1,+1),(0,+1)]

def hex_dist(a, b):
    aq, ar = a
    bq, br = b
    return max(abs(aq-bq), abs(ar-br), abs((aq+ar)-(bq+br)))


def a_star(start, goal, move_cost, penalty, blocked):
    """A* path-finding that respects blocked cells."""
    if goal in blocked or move_cost.get(goal) is None:
        return None
    open_q = [(hex_dist(start, goal), 0, start)]
    best = {start: 0};  came = {}
    while open_q:
        open_q.sort(key=lambda x: x[0])
        _, g, cur = open_q.pop(0)
        if cur == goal:
            path = [cur]
            while cur in came:
                cur = came[cur]; path.append(cur)
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
                best[nxt] = g2; came[nxt] = cur
                f = g2 + hex_dist(nxt, goal)
                heapq.heappush(open_q, (f, g2, nxt))
    return None

# ──────── registration ─────────────────────────────────────────────────--
def wait_register():
    global status_text
    deadline = time.time() + 5*60
    while time.time() < deadline:
        r = requests.post(URL + "/api/register", headers=HEADERS)
        if r.status_code == 200:
            status_text = "✓ registered, waiting start…"
            return True
        status_text = f"register {r.status_code}: {r.text.strip()}"
        time.sleep(5)
    status_text = "⨯ registration window closed"
    return False

# ──────── grid generation around the anthill ─────────────────────────────
def grid_layer(spot, radius):
    sx, sy = spot
    for dq in range(-radius, radius+1):
        for dr in range(-radius, radius+1):
            if max(abs(dq), abs(dr)) != radius:
                continue
            yield (sx + dq*GRID_STEP, sy + dr*GRID_STEP)

# ──────── main bot logic ─────────────────────────────────────────────────
def bot(renderer: ArenaRenderer):
    global status_text
    if not wait_register():
        sys.exit(1)

    known = {}
    mem_goal = {}
    last_turn = -1
    last_request = 0.0
    grid_cache = []
    next_radius = 0

    def throttle():
        nonlocal last_request
        now = time.time()
        if now - last_request < STEP_DELAY:
            time.sleep(STEP_DELAY - (now - last_request))
        last_request = time.time()

    while True:
        throttle()
        arena = requests.get(URL + "/api/arena", headers=HEADERS).json()
        renderer.set_state(arena)

        turn = arena.get("turnNo", -1)
        if turn == last_turn:
            continue
        last_turn = turn

        status_text = (f"turn {turn:>4}  "
                       f"A:{len(arena['ants'])}  "
                       f"F:{len(arena['food'])}")

        # ── map updates
        for c in arena.get("map", []):
            known[(c["q"], c["r"])] = c["type"]

        move_cost = {(q, r): (2 if t == 3 else 1) if t != 5 else None
                     for (q, r), t in known.items()}
        penalty   = {(q, r): ACID_PENALTY if t == 4 else 0
                     for (q, r), t in known.items()}

        spot      = (arena["spot"]["q"], arena["spot"]["r"])
        helpers   = [(h["q"], h["r"]) for h in arena.get("home", [])]
        if not helpers:
            helpers = [spot]
        resources = [(f["q"], f["r"]) for f in arena.get("food", [])]

        # extend grid for exploration
        while len(grid_cache) < len(arena["ants"]) * 2:
            next_radius += 1
            layer = [cell for cell in grid_layer(spot, next_radius)
                     if known.get(cell, 5) != 5]
            grid_cache.extend(layer)

        occupied   = {(a["q"], a["r"]) for a in arena["ants"]}
        reserved   = set()
        targeted_res  = set()
        targeted_grid = set()

        for a in arena["ants"]:
            tgt = mem_goal.get(a["id"])
            if tgt and tgt not in resources:
                targeted_grid.add(tgt)

        moves = []
        for ant in arena["ants"]:
            aid   = ant["id"]
            pos   = (ant["q"], ant["r"])
            typ   = ant["type"]
            laden = ant.get("food", {}).get("amount", 0) > 0

            # ── only workers gather food
            if typ == 1:
                if laden:                        # returning to base
                    goal = min(helpers, key=lambda h: hex_dist(pos, h))
                else:
                    free_res = [r for r in resources
                                if r not in targeted_res and r not in occupied]
                    if free_res:
                        goal = min(free_res, key=lambda r: hex_dist(pos, r))
                        targeted_res.add(goal)
                    else:                        # exploration
                        goal = mem_goal.get(aid)
                        if (goal in occupied or goal in targeted_grid or
                            goal is None or hex_dist(pos, goal) == 0):
                            for g in grid_cache:
                                if g not in occupied and g not in targeted_grid:
                                    goal = g
                                    break
                        targeted_grid.add(goal)
            else:
                goal = pos

            blocked = (occupied | reserved) - {pos}
            path = a_star(pos, goal, move_cost, penalty, blocked)
            step = pos if not path or len(path) == 1 else path[1]
            reserved.add(step)
            mem_goal[aid] = goal
            moves.append({"ant": aid,
                          "path": [{"q": step[0], "r": step[1]}]})

        throttle()
        requests.post(URL + "/api/move", headers=HEADERS, json={"moves": moves})

# ──────── viewer loop ─────────────────────────────────────────────────────
def main():
    global status_text
    pygame.init()
    screen   = pygame.display.set_mode((1280, 800), pygame.RESIZABLE)
    pygame.display.set_caption("Datspulse scatter bot")
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
