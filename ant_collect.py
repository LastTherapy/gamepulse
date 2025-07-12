#!/usr/bin/env python3
# ant_collect_avoid.py
# ─────────────────────────────────────────────────────────────────────────────
# • 20 × 20 карта. Каждый тик (1 с) спавнятся ресурсы.
# • Наш рабочий (speed = 4) собирает ближайший ресурс ⇒ база ⇒ снова ищет.
# • Новые препятствия
#     1. Клетка с **другим рабочим** (того же типа) = стенка.
#     2. Клетка с **вражеским муравьём** = стенка,
#        + все 6 соседних гексов получают penalty = 20
#        → путь старается не подходить близко.
# • Красная ломаная = оставшийся маршрут.
# • Управление:  LMB — таскать карту; Esc — выход.
# ----------------------------------------------------------------------------

import math, random, time, sys, pygame
from typing import Dict, Tuple, List, Set

# ───────── параметры ───────────────────────────────────────────────────────
HEX_SIZE = 28
GRID_W, GRID_H = 20, 20
FPS      = 60
TICK_SEC = 1.0
SPAWN_CHANCE = 0.15
MAX_RES     = 40
ANT_SPEED   = 4

#  name,  color,          move,  penalty
TERRAIN = {
    2: ("empty", (170,170,170), 1, 0),
    3: ("dirt",  (139, 84, 33), 2, 0),
    4: ("acid",  ( 20,170,230), 1, 5),
    5: ("stone", ( 60, 60, 60), None, None),
}

RES_CLR   = (255,215,0)
ANT_CLR   = (255,140,0)
FRIEND_CLR= ( 50,130,255)
ENEMY_CLR = (150,150,150)
PATH_CLR  = (220,40,40)
BASE_CLR  = (255,255,0)
BG, GRID  = (25,25,25), (60,60,60)
ENEMY_PEN = 20
SQRT3     = math.sqrt(3)

# ───────── геометрия ───────────────────────────────────────────────────────
DIRS = [(+1,0),(+1,-1),(0,-1),(-1,0),(-1,+1),(0,+1)]
def axial_px(q,r,s=HEX_SIZE): return s*1.5*q, s*SQRT3*(r+q/2)
def hex_pts(cx,cy,s=HEX_SIZE):
    return [(round(cx+s*math.cos(math.radians(a))),
             round(cy+s*math.sin(math.radians(a))))
            for a in range(0,360,60)]
def hex_dist(a,b):
    aq,ar=a; bq,br=b
    return max(abs(aq-bq),abs(ar-br),abs((aq+ar)-(bq+br)))

# ───────── A* c учётом move_cost и penalty ─────────────────────────────────
def a_star(start,goal,move_cost:Dict,penalty:Dict):
    open_l=[(hex_dist(start,goal),0,start)]
    best={start:0}; came={}
    while open_l:
        open_l.sort(key=lambda x:x[0])
        _,gpen,cur=open_l.pop(0)
        if cur==goal:
            path=[cur]
            while cur in came: cur=came[cur]; path.append(cur)
            return path[::-1]
        for dq,dr in DIRS:
            nxt=(cur[0]+dq,cur[1]+dr)
            mv=move_cost.get(nxt)
            if mv is None: continue           # стена
            g2=gpen+mv+penalty.get(nxt,0)
            if g2<best.get(nxt,1e9):
                best[nxt]=g2; came[nxt]=cur
                f=g2+hex_dist(nxt,goal)
                open_l.append((f,gpen+mv,nxt))
    return None

# ───────── генерация карты и объектов ──────────────────────────────────────
def make_map():
    mp={}
    for q in range(GRID_W):
        for r in range(GRID_H):
            mp[(q,r)] = random.choices([2,3,4,5],[70,15,10,5])[0]
    return mp

def random_free(world, occupied:Set):
    while True:
        pos=(random.randrange(GRID_W), random.randrange(GRID_H))
        if world[pos]!=5 and pos not in occupied:
            return pos

# ───────── main ────────────────────────────────────────────────────────────
def main():
    pygame.init()
    screen=pygame.display.set_mode((1200,900), pygame.RESIZABLE)
    pygame.display.set_caption("Ant collects & avoids enemies – drag LMB")

    world = make_map()
    base  = (GRID_W//2, GRID_H//2)
    ant   = {"pos":base, "carrying":False, "path":[]}          # наш рабочий

    # статические «друзья» того же типа (блокируют)
    friends:Set = { random_free(world,{base}) for _ in range(3) }

    # статические враги
    enemies:Set = { random_free(world,{base,*friends}) for _ in range(3) }

    resources:Set=set()
    offset=[120,120]; drag=False; m0=(0,0); o0=(0,0)
    clock=pygame.time.Clock(); last_tick=time.time()
    font=pygame.font.SysFont("consolas",14)

    def center(q,r): x,y=axial_px(q,r); return round(x+offset[0]),round(y+offset[1])

    def spawn_res():
        if len(resources)>=MAX_RES: return
        for (q,r),t in world.items():
            if t==5 or (q,r) in resources or (q,r) in friends or (q,r) in enemies: continue
            if random.random()<SPAWN_CHANCE:
                resources.add((q,r))

    def build_cost_tables():
        move_cost={pos:TERRAIN[t][2] for pos,t in world.items()}
        penalty  ={pos:TERRAIN[t][3] for pos,t in world.items()}
        # друзья блокируют
        for p in friends:
            move_cost[p]=None
        # враги блокируют + penalty вокруг
        for ex,ey in enemies:
            move_cost[(ex,ey)] = None
            for dq,dr in DIRS:
                adj=(ex+dq,ey+dr)
                if move_cost.get(adj) is not None:
                    penalty[adj]=penalty.get(adj,0)+ENEMY_PEN
        return move_cost, penalty

    move_cost, penalty = build_cost_tables()

    def plan_to(target):
        ant["path"]= (a_star(ant["pos"],target,move_cost,penalty) or [])[1:]

    spawn_res()
    if resources: plan_to(min(resources,key=lambda p:hex_dist(ant["pos"],p)))

    # ───────── игровой цикл ────────────────────────────────────────────────
    run=True
    while run:
        for e in pygame.event.get():
            if e.type==pygame.QUIT or (e.type==pygame.KEYDOWN and e.key==pygame.K_ESCAPE):
                run=False
            elif e.type==pygame.MOUSEBUTTONDOWN and e.button==1:
                drag=True; m0=e.pos; o0=tuple(offset)
            elif e.type==pygame.MOUSEBUTTONUP and e.button==1:
                drag=False
            elif e.type==pygame.MOUSEMOTION and drag:
                dx,dy=e.pos[0]-m0[0], e.pos[1]-m0[1]; offset=[o0[0]+dx,o0[1]+dy]

        # тик
        if time.time()-last_tick>=TICK_SEC:
            last_tick=time.time()
            spawn_res()
            move_cost, penalty = build_cost_tables()   # обновить (на случай динамики)

            speed=ANT_SPEED
            while speed>0 and ant["path"]:
                nxt=ant["path"][0]; mv=move_cost[nxt]
                if mv is None or mv>speed: break
                ant["pos"]=nxt; ant["path"].pop(0); speed-=mv

            if not ant["path"]:
                if ant["carrying"] and ant["pos"]==base:
                    ant["carrying"]=False
                elif (not ant["carrying"]) and ant["pos"] in resources:
                    resources.remove(ant["pos"]); ant["carrying"]=True

                if ant["carrying"]:
                    plan_to(base)
                elif resources:
                    plan_to(min(resources,key=lambda p:hex_dist(ant["pos"],p)))
                else:
                    ant["path"]=[]

        # ───────── рисование ──────────────────────────────────────────────
        screen.fill(BG)
        for (q,r),t in world.items():
            pygame.draw.polygon(screen,TERRAIN[t][1],hex_pts(*center(q,r)))
            pygame.draw.polygon(screen,GRID,hex_pts(*center(q,r)),1)

        for fq,fr in friends:
            pygame.draw.circle(screen, FRIEND_CLR, center(fq,fr), HEX_SIZE//2)

        for eq,er in enemies:
            pygame.draw.circle(screen, ENEMY_CLR, center(eq,er), HEX_SIZE//2)

        for rq,rr in resources:
            pygame.draw.circle(screen, RES_CLR, center(rq,rr), HEX_SIZE//3)

        if ant["path"]:
            pts=[center(*ant["pos"])] + [center(q,r) for q,r in ant["path"]]
            pygame.draw.lines(screen, PATH_CLR, False, pts, 4)

        cx,cy=center(*ant["pos"])
        pygame.draw.circle(screen, ANT_CLR, (cx,cy), HEX_SIZE//2)
        if ant["carrying"]:
            pygame.draw.circle(screen, RES_CLR, (cx+HEX_SIZE//2-6, cy-HEX_SIZE//2+6), 6)

        pygame.draw.circle(screen, BASE_CLR, center(*base), HEX_SIZE//2,3)

        hud=font.render(f"res={len(resources)}  carry={ant['carrying']}  path={len(ant['path'])}",True,(220,220,220))
        screen.blit(hud,(10,10))

        pygame.display.flip()
        pygame.time.Clock().tick(FPS)

    pygame.quit(); sys.exit()

if __name__=="__main__":
    main()
