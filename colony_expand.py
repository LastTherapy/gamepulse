#!/usr/bin/env python3
# colony_expand.py
# ─────────────────────────────────────────────────────────────────────────────
# • Рабочие появляются на spot с вероятностью 60 % / тик (до 50 шт).
# • Заполняют квадратную сетку, которая **автоматически расширяется**:
#       сначала 4 × 4, затем 6 × 6, 8 × 8 …
# • Несут ресурсы → выгружают строго на вспомогательные гексы (не на spot).
# • Кислоту стараются обходить (penalty = 5), но она проходима (1 ОП).
# • Ресурсы спавнятся реже (0.05) и максимум 30.
# • Цвета:  spot — фиолетовый, home helpers — жёлтые кольца.
# ----------------------------------------------------------------------------

import math, random, time, sys, pygame
from typing import Dict, Tuple, List, Set, Optional

# ───── параметры ───────────────────────────────────────────────────────────
HEX_SIZE          = 26
GRID_W, GRID_H    = 20, 20
FPS               = 60
TICK_SEC          = 1.0
WORKER_PROB       = 0.60       # шанс появления рабочего / тик
MAX_WORKERS       = 50
WORKER_SPEED      = 4

SPAWN_CHANCE      = 0.05       # ресурсы
MAX_RES           = 30

TERRAIN = {                     # name,        rgb,       move, pen
    2: ("empty", (170,170,170), 1, 0),
    3: ("dirt",  (139, 84, 33), 2, 0),
    4: ("acid",  ( 20,170,230), 1, 5),
    5: ("stone", ( 60, 60, 60), None, None),
}

RES_CLR   = (255,215,0)
WORK_CLR  = (255,140,0)
PATH_CLR  = (220,40,40)
SPOT_CLR  = (180, 60,250)      # фиолетовый
HELP_CLR  = (255,255,  0)      # жёлтый
BG, GRID  = (25,25,25), (60,60,60)
SQRT3     = math.sqrt(3)

# ───── геометрия ───────────────────────────────────────────────────────────
DIRS = [(+1,0),(+1,-1),(0,-1),(-1,0),(-1,+1),(0,+1)]
def axial_px(q,r,s=HEX_SIZE): return s*1.5*q, s*SQRT3*(r+q/2)
def hex_pts(cx,cy,s=HEX_SIZE):
    return [(round(cx+s*math.cos(math.radians(a))),
             round(cy+s*math.sin(math.radians(a))))
            for a in range(0,360,60)]
def hex_dist(a,b):
    aq,ar=a; bq,br=b
    return max(abs(aq-bq),abs(ar-br),abs((aq+ar)-(bq+br)))

# ───── A* ──────────────────────────────────────────────────────────────────
def a_star(start,goal,move_cost,penalty):
    if move_cost.get(goal) is None: return None
    open_l=[(hex_dist(start,goal),0,start)]
    best={start:0}; came={}
    while open_l:
        open_l.sort(key=lambda x:x[0])
        _, gp, cur=open_l.pop(0)
        if cur==goal:
            path=[cur]
            while cur in came: cur=came[cur]; path.append(cur)
            return path[::-1]
        for dq,dr in DIRS:
            nxt=(cur[0]+dq,cur[1]+dr)
            mv=move_cost.get(nxt)
            if mv is None: continue
            g2=gp+mv+penalty.get(nxt,0)
            if g2<best.get(nxt,1e9):
                best[nxt]=g2; came[nxt]=cur
                f=g2+hex_dist(nxt,goal)
                open_l.append((f,gp+mv,nxt))
    return None

# ───── генерация карты ─────────────────────────────────────────────────────
def make_map():
    mp={}
    for q in range(GRID_W):
        for r in range(GRID_H):
            mp[(q,r)] = random.choices([2,3,4,5],[70,15,10,5])[0]
    return mp

# ───── утилиты ─────────────────────────────────────────────────────────────
def random_free(world, taken:Set):
    while True:
        p=(random.randrange(GRID_W), random.randrange(GRID_H))
        if world[p]!=5 and p not in taken: return p

def draw_hex(screen, color, cx, cy):
    pygame.draw.polygon(screen,color,hex_pts(cx,cy))
    pygame.draw.polygon(screen,GRID,hex_pts(cx,cy),1)

# ───── main ────────────────────────────────────────────────────────────────
def main():
    pygame.init()
    screen=pygame.display.set_mode((1200,900), pygame.RESIZABLE)
    pygame.display.set_caption("Expanding grid colony")

    world = make_map()
    move_cost={pos:TERRAIN[t][2] for pos,t in world.items()}
    penalty  ={pos:TERRAIN[t][3] for pos,t in world.items()}

    spot=(GRID_W//2, GRID_H//2)          # центр
    helpers=[(spot[0]-1,spot[1]), (spot[0],spot[1]-1)]
    workers=[]                           # [{'pos', 'carrying', 'path', 'target'}]
    resources:Set=set()

    grid_radius=2                        # половина текущего квадрата (4×4)

    offset=[150,150]; drag=False; m0=o0=(0,0)
    clock=pygame.time.Clock(); last_tick=time.time()
    font=pygame.font.SysFont("consolas",14)

    # ── функции ------------------------------------------------------------
    def center(q,r): x,y=axial_px(q,r); return round(x+offset[0]),round(y+offset[1])

    def spawn_resource():
        if len(resources)>=MAX_RES: return
        for (q,r),t in world.items():
            if t==5 or (q,r) in resources: continue
            if random.random()<SPAWN_CHANCE and (q,r) not in {w['pos'] for w in workers}:
                resources.add((q,r))

    def spawn_worker():
        if len(workers)>=MAX_WORKERS: return
        if random.random()<=WORKER_PROB:
            workers.append({"pos":spot,"carrying":False,"path":[],"target":None})

    def grid_cells(radius):
        for dq in range(-radius,radius):
            for dr in range(-radius,radius):
                yield (spot[0]+dq, spot[1]+dr)

    def choose_grid_target():
        taken={tuple(w['target']) for w in workers if w['target'] and not w['carrying']}
        for cell in grid_cells(grid_radius):
            if world.get(cell,5)==5: continue
            if cell in taken: continue
            return cell
        return None

    def expand_grid_if_needed():
        nonlocal grid_radius
        needed=sum(1 for cell in grid_cells(grid_radius) if world.get(cell,5)!=5)
        assigned=sum(1 for w in workers if w['target'] and not w['carrying'] and w['target'] in grid_cells(grid_radius))
        if assigned>=needed:
            grid_radius+=1

    def plan(w, goal):
        path=a_star(w['pos'], goal, move_cost, penalty)
        w['path']=path[1:] if path else []
        w['target']=goal

    # ── начальный рес -------------------------------------------------------
    spawn_resource()

    # ── цикл ----------------------------------------------------------------
    running=True
    while running:
        for e in pygame.event.get():
            if e.type==pygame.QUIT or (e.type==pygame.KEYDOWN and e.key==pygame.K_ESCAPE):
                running=False
            elif e.type==pygame.MOUSEBUTTONDOWN and e.button==1:
                drag=True; m0=e.pos; o0=tuple(offset)
            elif e.type==pygame.MOUSEBUTTONUP and e.button==1:
                drag=False
            elif e.type==pygame.MOUSEMOTION and drag:
                dx,dy=e.pos[0]-m0[0], e.pos[1]-m0[1]; offset=[o0[0]+dx,o0[1]+dy]

        if time.time()-last_tick>=TICK_SEC:
            last_tick=time.time()
            spawn_resource(); spawn_worker()

            for w in workers:
                speed=WORKER_SPEED
                while speed>0 and w['path']:
                    nxt=w['path'][0]; mv=move_cost[nxt]
                    if mv is None or mv>speed: break
                    w['pos']=nxt; w['path'].pop(0); speed-=mv

                if not w['path']:
                    if w['carrying'] and w['pos'] in helpers:
                        w['carrying']=False
                    elif (not w['carrying']) and w['pos'] in resources:
                        resources.remove(w['pos']); w['carrying']=True

                    if w['carrying']:
                        plan(w, random.choice(helpers))
                    elif resources:
                        nearest=min(resources, key=lambda p:hex_dist(w['pos'],p))
                        plan(w, nearest)
                    else:
                        tgt=choose_grid_target()
                        if tgt: plan(w,tgt)

            expand_grid_if_needed()

        # ─── отрисовка —────────────────────────────────────────────────────
        screen.fill(BG)
        for (q,r),t in world.items():
            draw_hex(screen,TERRAIN[t][1],*center(q,r))

        # дом
        pygame.draw.circle(screen, SPOT_CLR, center(*spot), HEX_SIZE//2,3)
        for h in helpers:
            pygame.draw.circle(screen, HELP_CLR, center(*h), HEX_SIZE//2,2)

        # ресурсы
        for rq,rr in resources: pygame.draw.circle(screen, RES_CLR, center(rq,rr), HEX_SIZE//3)

        # пути
        for w in workers:
            if w['path']:
                pts=[center(*w['pos'])]+[center(q,r) for q,r in w['path']]
                pygame.draw.lines(screen, PATH_CLR, False, pts, 3)

        # рабочие
        for w in workers:
            cx,cy=center(*w['pos'])
            pygame.draw.circle(screen, WORK_CLR, (cx,cy), HEX_SIZE//2)
            if w['carrying']:
                pygame.draw.circle(screen, RES_CLR, (cx+HEX_SIZE//2-6, cy-HEX_SIZE//2+6),6)

        hud=font.render(f"W={len(workers)} R={len(resources)} Grid={grid_radius*2}×{grid_radius*2}",True,(220,220,220))
        screen.blit(hud,(10,10))

        pygame.display.flip()
        clock.tick(FPS)

    pygame.quit(); sys.exit()

if __name__=="__main__":
    main()
