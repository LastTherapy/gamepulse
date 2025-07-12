from __future__ import annotations

from dataclasses import dataclass, field
from typing import Tuple, Optional, List, Dict, Set
import random

# ---------------------------------------------------------------------------
# Hex geometry helpers
# ---------------------------------------------------------------------------
DIRECTIONS = [(1,0), (1,-1), (0,-1), (-1,0), (-1,1), (0,1)]

def hex_add(a:Tuple[int,int], b:Tuple[int,int]) -> Tuple[int,int]:
    return a[0]+b[0], a[1]+b[1]

def hex_scale(a:Tuple[int,int], k:int) -> Tuple[int,int]:
    return a[0]*k, a[1]*k

def hex_dist(a:Tuple[int,int], b:Tuple[int,int]) -> int:
    aq, ar = a
    bq, br = b
    return max(abs(aq-bq), abs(ar-br), abs((aq+ar)-(bq+br)))

# Simple A* path-finding ----------------------------------------------------
def a_star_path(start:Tuple[int,int], goal:Tuple[int,int],
                move_cost:Dict[Tuple[int,int],int],
                penalty:Dict[Tuple[int,int],int],
                blocked:Set[Tuple[int,int]]|None=None) -> Optional[List[Tuple[int,int]]]:
    if blocked is None:
        blocked=set()
    if move_cost.get(goal) is None or goal in blocked:
        return None
    open_q=[(hex_dist(start, goal),0,start)]
    best={start:0}; came={}
    while open_q:
        open_q.sort(key=lambda x:x[0])
        _,g,cur=open_q.pop(0)
        if cur==goal:
            path=[cur]
            while cur in came:
                cur=came[cur]; path.append(cur)
            return path[::-1]
        for dq,dr in DIRECTIONS:
            nxt=(cur[0]+dq, cur[1]+dr)
            if nxt in blocked and nxt!=goal:
                continue
            mv=move_cost.get(nxt)
            if mv is None:
                continue
            g2=g+mv+penalty.get(nxt,0)
            if g2<best.get(nxt,1e9):
                best[nxt]=g2; came[nxt]=cur
                f=g2+hex_dist(nxt, goal)
                open_q.append((f,g2,nxt))
    return None

# Breadth-first search for food around start --------------------------------
def search_for_food(start:Tuple[int,int], foods:Set[Tuple[int,int]],
                    move_cost:Dict[Tuple[int,int],int], radius:int=4) -> Optional[Tuple[int,int]]:
    frontier=[start]; visited={start}; dist=0
    while frontier and dist<=radius:
        nxt=[]
        for pos in frontier:
            if pos in foods:
                return pos
            for dq,dr in DIRECTIONS:
                nb=(pos[0]+dq, pos[1]+dr)
                if nb in visited:
                    continue
                if move_cost.get(nb) is None:
                    continue
                visited.add(nb); nxt.append(nb)
        frontier=nxt; dist+=1
    return None

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------
@dataclass
class Slot:
    coord: Tuple[int,int]
    role: str
    ant_id: Optional[int]=None

@dataclass
class Ant:
    id: int
    type: str
    pos: Tuple[int,int]
    state: str='to_station'
    target: Optional[Tuple[int,int]]=None
    path: List[Tuple[int,int]] = field(default_factory=list)
    cargo: int = 0

    def step_path(self) -> Tuple[int,int]:
        return self.path[0] if self.path else self.pos

# ---------------------------------------------------------------------------
# Slot generation
# ---------------------------------------------------------------------------
def generate_slots(base_coord:Tuple[int,int], home_hexes:List[Tuple[int,int]], k:int=1):
    scout_slots: List[Slot]=[]
    worker_slots: List[Slot]=[]
    guard_slots: List[Slot]=[]
    radius=4*k
    # scout corners
    for i,(dq,dr) in enumerate(DIRECTIONS):
        corner=(base_coord[0]+dq*radius, base_coord[1]+dr*radius)
        scout_slots.append(Slot(corner,'scout'))
        worker_slots.append(Slot(corner,'worker'))
        ndq,ndr=DIRECTIONS[(i+1)%6]
        edge=(base_coord[0]+dq*radius+ndq*radius//2,
              base_coord[1]+dr*radius+ndr*radius//2)
        worker_slots.append(Slot(edge,'worker'))
    # guard around homes
    for h in home_hexes:
        if h==base_coord:
            continue
        for dq,dr in DIRECTIONS:
            c=(h[0]+dq, h[1]+dr)
            if c==base_coord:
                continue
            if c not in [sl.coord for sl in guard_slots]:
                guard_slots.append(Slot(c,'soldier'))
    return scout_slots, worker_slots, guard_slots

# ---------------------------------------------------------------------------
# Ant types
# ---------------------------------------------------------------------------
class WorkerAnt(Ant):
    SEARCH_INTERVAL=5

    def update(self, tick:int, move_cost, penalty, foods:Set[Tuple[int,int]], home_hexes:List[Tuple[int,int]]):
        # to_station -> idle
        if self.state=='to_station' and self.pos==self.target:
            self.state='idle'

        if self.state=='idle':
            if tick % self.SEARCH_INTERVAL==0:
                food=search_for_food(self.target, foods, move_cost)
                if food:
                    self.repath(food, move_cost, penalty)
                    self.state='to_food'
        elif self.state=='to_food':
            if self.pos==self.target:
                if self.pos in foods:
                    foods.remove(self.pos)
                    self.cargo=1
                    self.state='carry'
                else:
                    self.state='idle'
        elif self.state=='carry':
            home=min([h for h in home_hexes if h!=self.target] or home_hexes,
                      key=lambda h: hex_dist(self.pos,h))
            self.repath(home, move_cost, penalty)
            self.state='to_deposit'
        elif self.state=='to_deposit':
            if self.pos==self.target:
                self.cargo=0
                self.repath(self.station, move_cost, penalty)
                self.state='to_station'

    def repath(self, new_target:Tuple[int,int], move_cost, penalty):
        self.target=new_target
        blocked=set()
        self.path=(a_star_path(self.pos, new_target, move_cost, penalty, blocked) or [])[1:]

    @property
    def station(self):
        return getattr(self,'_station',self.target)
    @station.setter
    def station(self,val):
        self._station=val

class ScoutAnt(Ant):
    def update(self, move_cost, penalty, foods:Set[Tuple[int,int]], home_hexes:List[Tuple[int,int]]):
        if self.state=='to_station' and self.pos==self.target:
            self.state='sentry'
        if self.state=='sentry':
            if self.pos in foods:
                foods.remove(self.pos)
                self.cargo=1
                home=min([h for h in home_hexes if h!=self.pos] or home_hexes,
                          key=lambda h: hex_dist(self.pos,h))
                self.repath(home, move_cost, penalty)
                self.state='carry'
        elif self.state=='carry':
            if self.pos==self.target:
                self.cargo=0
                self.repath(self.station, move_cost, penalty)
                self.state='sentry'

    def repath(self, new_target:Tuple[int,int], move_cost, penalty):
        self.target=new_target
        self.path=(a_star_path(self.pos,new_target,move_cost,penalty,set()) or [])[1:]

    @property
    def station(self):
        return getattr(self,'_station',self.target)
    @station.setter
    def station(self,val):
        self._station=val

class SoldierAnt(Ant):
    def __init__(self, ant_id:int, pos:Tuple[int,int]):
        super().__init__(ant_id,'soldier',pos)
        self.enemy:Optional[Tuple[int,int]]=None

    def update(self, visible_enemies:List[Tuple[int,int]], move_cost, penalty):
        if self.state=='to_guard' and self.pos==self.target:
            self.state='guard'
        if self.state=='guard':
            if visible_enemies:
                goal=min(visible_enemies, key=lambda e: hex_dist(self.pos,e))
                self.enemy=goal
                self.repath(goal, move_cost, penalty)
                self.state='hunt'
        elif self.state=='hunt':
            if self.enemy not in visible_enemies:
                self.repath(self.station, move_cost, penalty)
                self.state='guard'

    def repath(self, new_target:Tuple[int,int], move_cost, penalty):
        self.target=new_target
        self.path=(a_star_path(self.pos,new_target,move_cost,penalty,set()) or [])[1:]

    @property
    def station(self):
        return getattr(self,'_station',self.target)
    @station.setter
    def station(self,val):
        self._station=val

# ---------------------------------------------------------------------------
# Simple simulation engine
# ---------------------------------------------------------------------------
class Game:
    def __init__(self, size:int=20):
        self.size=size
        self.map={(q,r):2 for q in range(size) for r in range(size)}
        self.move_cost={pos:1 for pos in self.map}
        self.penalty={pos:0 for pos in self.map}
        self.tick=0
        self.spawn=(size//2, size//2)
        self.home=[self.spawn, (self.spawn[0]+1,self.spawn[1]), (self.spawn[0],self.spawn[1]+1)]
        s,w,g=generate_slots(self.spawn,self.home)
        self.scout_slots=s; self.worker_slots=w; self.guard_slots=g
        self.ants:Dict[int,Ant]={}
        self.foods:set=set()
        self.next_id=1
        self.init_ants()

    def init_ants(self):
        # one of each type
        if self.worker_slots:
            sl=self.worker_slots[0]; sl.ant_id=self.next_id
            a=WorkerAnt(self.next_id,self.spawn)
            a.station=sl.coord
            a.target=sl.coord
            self.ants[self.next_id]=a
            self.next_id+=1
        if self.scout_slots:
            sl=self.scout_slots[0]; sl.ant_id=self.next_id
            a=ScoutAnt(self.next_id,self.spawn)
            a.station=sl.coord
            a.target=sl.coord
            self.ants[self.next_id]=a
            self.next_id+=1
        if self.guard_slots:
            sl=self.guard_slots[0]; sl.ant_id=self.next_id
            a=SoldierAnt(self.next_id,self.spawn)
            a.station=sl.coord
            a.target=sl.coord
            a.state='to_guard'
            self.ants[self.next_id]=a
            self.next_id+=1

    def spawn_food(self, count:int=3):
        for _ in range(count):
            p=(random.randrange(self.size), random.randrange(self.size))
            if self.map.get(p)!=2:
                continue
            if p in self.foods or p in [a.pos for a in self.ants.values()]:
                continue
            self.foods.add(p)

    # -------------------------------------------------------------
    def game_tick(self):
        self.tick+=1
        self.spawn_food(1)
        # --- fsm update ---
        for ant in self.ants.values():
            if isinstance(ant, WorkerAnt):
                ant.update(self.tick, self.move_cost, self.penalty, self.foods, self.home)
            elif isinstance(ant, ScoutAnt):
                ant.update(self.move_cost, self.penalty, self.foods, self.home)
            elif isinstance(ant, SoldierAnt):
                ant.update([], self.move_cost, self.penalty)

        # --- reservation ---
        claims:Dict[Tuple[int,int],List[int]]={}
        steps:Dict[int,Tuple[int,int]]={}
        for aid,ant in self.ants.items():
            nxt=ant.step_path()
            if isinstance(ant,SoldierAnt) and ant.state=='guard' and not ant.path:
                steps[aid]=ant.pos
                continue
            claims.setdefault(nxt,[]).append(aid)
            steps[aid]=nxt
        # --- resolve conflicts ---
        for cell,ids in claims.items():
            if len(ids)>1:
                for aid in ids:
                    steps[aid]=self.ants[aid].pos
                    self.ants[aid].path=[]
        # --- move ---
        for aid,pos in steps.items():
            ant=self.ants[aid]
            if pos!=ant.pos:
                ant.pos=pos
                if ant.path and ant.path[0]==pos:
                    ant.path.pop(0)
        # cleanup none

    # -------------------------------------------------------------
    def to_json(self):
        js={
            'turnNo':self.tick,
            'score':0,
            'nextTurnIn':0.0,
            'map':[{'q':q,'r':r,'type':t} for (q,r),t in self.map.items()],
            'home':[{'q':q,'r':r} for q,r in self.home],
            'spot':{'q':self.spawn[0],'r':self.spawn[1]},
            'ants':[{'id':a.id,'q':a.pos[0],'r':a.pos[1],
                     'type':0 if a.type=='worker' else 1 if a.type=='soldier' else 2,
                     'food':{'amount':a.cargo,'type':1} , 'health':100} for a in self.ants.values()],
            'enemies':[],
            'food':[{'q':q,'r':r,'type':1,'amount':1} for q,r in self.foods]
        }
        return js

# ---------------------------------------------------------------------------
# Demo runner with ArenaRenderer
# ---------------------------------------------------------------------------
def main():
    import pygame
    from datspulse_viewer import ArenaRenderer

    pygame.init()
    screen=pygame.display.set_mode((1280,800))
    pygame.display.set_caption("Ant simulation")
    renderer=ArenaRenderer(screen)

    game=Game()
    renderer.set_state(game.to_json())

    clock=pygame.time.Clock()
    running=True
    while running:
        for e in pygame.event.get():
            if e.type==pygame.QUIT or (e.type==pygame.KEYDOWN and e.key==pygame.K_ESCAPE):
                running=False
            renderer.handle_event(e)
        game.game_tick()
        renderer.set_state(game.to_json())
        renderer.draw()
        pygame.display.flip()
        clock.tick(5)
    pygame.quit()

if __name__=='__main__':
    main()
