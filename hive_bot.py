#!/usr/bin/env python3
"""Ant hive bot implementing slot assignment and simple FSM.

This module demonstrates the algorithm described in the repository
specification: workers collect food, scouts stay on sentry points and
soldiers guard the colony.  The bot communicates with the Datspulse
Arena API, but the logic is self-contained and independent from the
viewer utilities.
"""

from __future__ import annotations

import heapq
import time
import requests
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# ─── API settings ───────────────────────────────────────────────────────────
URL = "https://games-test.datsteam.dev"
TOKEN = "39413815-04e3-4ba6-b21e-ad5c29ca2cee"
HEADERS = {"accept": "application/json", "X-Auth-Token": TOKEN}

# speed limit for requests
MAX_RPS = 1.5
STEP_DELAY = 1 / MAX_RPS

# ─── geometry helpers ───────────────────────────────────────────────────────
DIRS = [(+1,0),(+1,-1),(0,-1),(-1,0),(-1,+1),(0,+1)]

def hex_dist(a:Tuple[int,int], b:Tuple[int,int]) -> int:
    aq, ar = a
    bq, br = b
    return max(abs(aq-bq), abs(ar-br), abs((aq+ar)-(bq+br)))

# ─── path-finding ------------------------------------------------------------

def a_star(start:Tuple[int,int], goal:Tuple[int,int], move_cost:Dict,
           penalty:Dict, blocked:set) -> Optional[List[Tuple[int,int]]]:
    """Classic A* for hex maps."""
    if goal in blocked or move_cost.get(goal) is None:
        return None
    open_q = [(hex_dist(start, goal), 0, start)]
    best   = {start: 0}; came = {}
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


def bfs_nearest_food(start:Tuple[int,int], foods:set, move_cost:Dict,
                     radius:int=4) -> Optional[Tuple[int,int]]:
    """Breadth-first search for food within limited radius."""
    frontier = [start]; visited = {start}; dist = 0
    while frontier and dist <= radius:
        next_f = []
        for pos in frontier:
            if pos in foods:
                return pos
            for dq, dr in DIRS:
                nxt = (pos[0]+dq, pos[1]+dr)
                if nxt in visited:
                    continue
                if move_cost.get(nxt) is None:
                    continue
                visited.add(nxt); next_f.append(nxt)
        frontier = next_f; dist += 1
    return None

# ─── data classes ------------------------------------------------------------

@dataclass
class Slot:
    coord: Tuple[int,int]
    role: str               # 'scout', 'worker' or 'guard'
    ant_id: Optional[str] = None

@dataclass
class Ant:
    id: str
    type: int
    state: str
    target: Tuple[int,int]
    path: List[Tuple[int,int]] = field(default_factory=list)
    cargo: int = 0

# ─── slot table generation ---------------------------------------------------

def build_slots(spot:Tuple[int,int], helpers:List[Tuple[int,int]]) -> Tuple[List[Slot],List[Slot],List[Slot]]:
    scout_slots: List[Slot] = []
    worker_slots: List[Slot] = []
    guard_slots:  List[Slot] = []

    # scouts/workers occupy rings radius 4*k
    radius = 4
    while len(scout_slots) < 50:      # sane limit for demo
        for i, (dq,dr) in enumerate(DIRS):
            corner = (spot[0] + dq*radius, spot[1] + dr*radius)
            scout_slots.append(Slot(corner, 'scout'))
            worker_slots.append(Slot(corner, 'worker'))
            # center of edge between this and next corner
            ndq,ndr = DIRS[(i+1)%6]
            edge = (spot[0] + dq*radius + ndq*radius//2,
                    spot[1] + dr*radius + ndr*radius//2)
            worker_slots.append(Slot(edge, 'worker'))
        radius += 4

    # guards around helper cells (excluding spawn)
    for h in helpers:
        if h == spot:
            continue
        for dq, dr in DIRS:
            coord = (h[0]+dq, h[1]+dr)
            guard_slots.append(Slot(coord, 'guard'))

    return scout_slots, worker_slots, guard_slots

# ─── bot implementation ------------------------------------------------------

def wait_register() -> bool:
    deadline = time.time() + 5*60
    while time.time() < deadline:
        r = requests.post(URL + "/api/register", headers=HEADERS)
        if r.status_code == 200:
            return True
        time.sleep(5)
    return False


class HiveBot:
    def __init__(self):
        self.ants: Dict[str, Ant] = {}
        self.scout_slots: List[Slot] = []
        self.worker_slots: List[Slot] = []
        self.guard_slots:  List[Slot] = []
        self.move_cost: Dict = {}
        self.penalty: Dict = {}
        self.last_request = 0.0

    # ─── helpers -------------------------------------------------------------
    def throttle(self):
        now = time.time()
        if now - self.last_request < STEP_DELAY:
            time.sleep(STEP_DELAY - (now - self.last_request))
        self.last_request = time.time()

    def update_map(self, arena:Dict):
        self.move_cost = {(c['q'], c['r']): (2 if c['type']==3 else 1) if c['type']!=5 else None
                          for c in arena['map']}
        self.penalty   = {(c['q'], c['r']): 5 if c['type']==4 else 0
                          for c in arena['map']}

    # ─── slot assignment -----------------------------------------------------
    def spawn_phase(self, arena:Dict):
        active_ids = {a['id'] for a in arena['ants']}
        # free slots from dead ants
        for slot in self.scout_slots + self.worker_slots + self.guard_slots:
            if slot.ant_id and slot.ant_id not in active_ids:
                slot.ant_id = None
        # detect new ants
        for a in arena['ants']:
            if a['id'] not in self.ants:
                self.assign_slot(a)

    def assign_slot(self, ant_js:Dict):
        aid = ant_js['id']
        atype = ant_js['type']
        if atype == 1:                # worker
            for sl in self.worker_slots:
                if sl.ant_id is None:
                    sl.ant_id = aid
                    self.ants[aid] = Ant(aid, atype, 'to_station', sl.coord)
                    return
        elif atype == 2:              # scout
            for sl in self.scout_slots:
                if sl.ant_id is None:
                    sl.ant_id = aid
                    self.ants[aid] = Ant(aid, atype, 'to_station', sl.coord)
                    return
        elif atype == 3:              # soldier
            for sl in self.guard_slots:
                if sl.ant_id is None:
                    sl.ant_id = aid
                    self.ants[aid] = Ant(aid, atype, 'to_guard', sl.coord)
                    return
            for sl in self.scout_slots:
                if sl.ant_id is None:
                    sl.ant_id = aid
                    self.ants[aid] = Ant(aid, atype, 'to_guard', sl.coord)
                    return
        # fallback
        self.ants[aid] = Ant(aid, atype, 'idle', ant_js['q'], [])

    # ─── fsm step ------------------------------------------------------------
    def fsm_update(self, arena:Dict):
        food = {(f['q'], f['r']) for f in arena['food']}
        homes = [(h['q'], h['r']) for h in arena['home'] if (h['q'],h['r']) != arena['spot']]
        enemies = {(e['q'], e['r']) for e in arena['enemies']}

        occupied = {(a['q'], a['r']) for a in arena['ants']}
        id_to_pos = {a['id']:(a['q'],a['r']) for a in arena['ants']}

        for aid, ant in self.ants.items():
            pos = id_to_pos.get(aid, ant.target)
            ant.cargo = next((a['food']['amount'] for a in arena['ants'] if a['id']==aid), 0)

            if ant.type == 1:                    # Worker
                if ant.state == 'to_station':
                    if pos == ant.target:
                        ant.state = 'idle'
                elif ant.state == 'idle':
                    tgt = bfs_nearest_food(ant.target, food, self.move_cost)
                    if tgt:
                        ant.state = 'to_food'; ant.path = a_star(pos, tgt, self.move_cost, self.penalty, occupied)
                    else:
                        ant.path = []
                elif ant.state == 'to_food':
                    if pos == ant.target and pos not in food:
                        ant.state = 'idle'
                    elif pos == ant.target and pos in food:
                        ant.state = 'carry'
                elif ant.state == 'carry':
                    home = min(homes, key=lambda h: hex_dist(pos, h)) if homes else arena['spot']
                    ant.path = a_star(pos, home, self.move_cost, self.penalty, occupied)
                    ant.state = 'to_deposit'
                elif ant.state == 'to_deposit':
                    if ant.cargo == 0:
                        ant.state = 'to_station'
                        ant.path = a_star(pos, ant.target, self.move_cost, self.penalty, occupied)

            elif ant.type == 2:                  # Scout
                if ant.state == 'to_station' and pos == ant.target:
                    ant.state = 'sentry'
                if ant.cargo > 0 and ant.state == 'sentry':
                    home = min(homes, key=lambda h: hex_dist(pos, h)) if homes else arena['spot']
                    ant.path = a_star(pos, home, self.move_cost, self.penalty, occupied)
                    ant.state = 'to_deposit'
                elif ant.state == 'to_deposit' and ant.cargo == 0:
                    ant.path = a_star(pos, ant.target, self.move_cost, self.penalty, occupied)
                    ant.state = 'sentry'

            elif ant.type == 3:                  # Soldier
                if ant.state == 'to_guard' and pos == ant.target:
                    ant.state = 'guard'
                if ant.state == 'guard' and enemies:
                    goal = min(enemies, key=lambda e: hex_dist(pos, e))
                    ant.path = a_star(pos, goal, self.move_cost, self.penalty, occupied)
                    ant.state = 'hunt'
                elif ant.state == 'hunt':
                    if not enemies:
                        ant.path = a_star(pos, ant.target, self.move_cost, self.penalty, occupied)
                        ant.state = 'guard'

    # ─── reservation & move planning ---------------------------------------
    def plan_moves(self, arena:Dict) -> List[Dict]:
        id_to_pos = {a['id']:(a['q'],a['r']) for a in arena['ants']}
        occupied = {(a['q'], a['r']) for a in arena['ants']}
        claims: Dict[Tuple[int,int], List[str]] = {}
        steps: Dict[str, Tuple[int,int]] = {}
        for aid, ant in self.ants.items():
            pos = id_to_pos.get(aid, ant.target)
            if ant.path:
                step = ant.path[1] if len(ant.path) > 1 else ant.path[0]
            else:
                step = pos
            if step in claims:
                claims[step].append(aid)
            else:
                claims[step] = [aid]
            steps[aid] = step

        # resolve conflicts
        for cell, ids in claims.items():
            if len(ids) > 1:
                for aid in ids:
                    steps[aid] = id_to_pos.get(aid, self.ants[aid].target)
                    self.ants[aid].path = []

        moves = []
        for aid, step in steps.items():
            moves.append({"ant": aid, "path": [{"q": step[0], "r": step[1]}]})
        return moves

    # ─── main loop -----------------------------------------------------------
    def run(self):
        if not wait_register():
            return
        arena = requests.get(URL + "/api/arena", headers=HEADERS).json()
        spot = (arena['spot']['q'], arena['spot']['r'])
        helpers = [(h['q'], h['r']) for h in arena['home']]
        self.scout_slots, self.worker_slots, self.guard_slots = build_slots(spot, helpers)

        while True:
            self.throttle()
            arena = requests.get(URL + "/api/arena", headers=HEADERS).json()
            self.update_map(arena)
            self.spawn_phase(arena)
            self.fsm_update(arena)
            moves = self.plan_moves(arena)
            self.throttle()
            requests.post(URL + "/api/move", headers=HEADERS, json={"moves": moves})


def main():
    bot = HiveBot()
    bot.run()


if __name__ == "__main__":
    main()
