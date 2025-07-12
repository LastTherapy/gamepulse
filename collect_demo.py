#!/usr/bin/env python3
# collect_demo_speed.py
# ─────────────────────────────────────────────────────────────────────────────
# • Случайная 20 × 20 карта (flat-top гексы)
# • Ресурсы случайно появляются каждый тик
# • Один рабочий муравей (speed = 4 очка хода)
#     ▸ тратит стоимость клетки (грязь = 2, кислота = 15, камень = ∞)
#     ▸ за один «тик-секунду» проходит столько клеток, сколько хватает скорости
#     ▸ забирает ресурс, возвращается на базу, выгружает и ищет следующий
# • Красная ломаная показывает оставшийся маршрут
# • ЛКМ — перетаскивание карты; Esc — выход
# ----------------------------------------------------------------------------

import math, random, pygame, sys, time
from typing import Dict, Tuple, List, Set

# ───────── настройки ────────────────────────────────────────────────────────
HEX_SIZE         = 28
GRID_W, GRID_H   = 20, 20
FPS              = 60
SPAWN_CHANCE     = 0.15
MAX_RESOURCES    = 40
ANT_SPEED        = 4           # очков движения за тик

TERRAIN = {
    2: ("empty",  (170,170,170),  1),
    3: ("dirt",   (139, 84, 33),  2),
    4: ("acid",   ( 20,170,230), 15),
    5: ("stone",  ( 60, 60, 60), None),   # стена
}
RES_CLR = (255,215,0)
ANT_CLR = (255,140,0)
PATH_CLR= (220,40,40)
BASE_CLR= (255,255,0)
BG, GRID = (25,25,25), (60,60,60)
SQRT3    = math.sqrt(3)

# ───────── геометрия ────────────────────────────────────────────────────────
DIRS = [(+1,0),(+1,-1),(0,-1),(-1,0),(-1,+1),(0,+1)]
def axial_px(q,r,s=HEX_SIZE): return s*1.5*q, s*SQRT3*(r+q/2)
def hex_pts(cx,cy,s=HEX_SIZE):
    return [(round(cx+s*math.cos(math.radians(a))),
             round(cy+s*math.sin(math.radians(a)))) for a in range(0,360,60)]
def hex_dist(a,b):
    aq,ar=a; bq,br=b
    return max(abs(aq-bq),abs(ar-br),abs((aq+ar)-(bq+br)))

# ───────── A* ───────────────────────────────────────────────────────────────
def a_star(start,goal,cost_of):
    open_l=[(hex_dist(start,goal),0,start)]
    g={start:0}; came={}
    while open_l:
        open_l.sort(key=lambda x:x[0])
        _,gcur,cur=open_l.pop(0)
        if cur==goal:
            path=[cur]
            while cur in came: cur=came[cur]; path.append(cur)
            return path[::-1]
        for dq,dr in DIRS:
            nxt=(cur[0]+dq,cur[1]+dr)
            c=cost_of.get(nxt)
            if c is None: continue
            g2=gcur+c
            if g2<g.get(nxt,1e9):
                came[nxt]=cur; g[nxt]=g2
                open_l.append((g2+hex_dist(nxt,goal),g2,nxt))
    return None

# ───────── генерация карты ─────────────────────────────────────────────────
def make_map():
    mp={}
    for q in range(GRID_W):
        for r in range(GRID_H):
            t=random.choices([2,3,4,5],[70,15,10,5])[0]
            mp[(q,r)]=t
    return mp

# ───────── main ────────────────────────────────────────────────────────────
def main():
    pygame.init()
    screen=pygame.display.set_mode((1200,900), pygame.RESIZABLE)
    pygame.display.set_caption("Ant path with speed – drag LMB")

    world = make_map()
    cost  = {pos:TERRAIN[t][2] for pos,t in world.items()}
    base  = (GRID_W//2, GRID_H//2)
    ant   = {"pos":base, "has":False, "path":[]}   # path — оставшиеся клетки
    resources:Set[Tuple[int,int]] = set()

    offset=[100,100]; drag=False; m0=(0,0); o0=(0,0)
    clock=pygame.time.Clock(); last_tick=time.time()
    font=pygame.font.SysFont("consolas",14)

    def center(q,r): x,y=axial_px(q,r); return round(x+offset[0]), round(y+offset[1])

    def spawn_resources():
        if len(resources) >= MAX_RESOURCES: return
        for (q,r),t in world.items():
            if random.random()<SPAWN_CHANCE and t!=5 and (q,r)!=ant["pos"] and (q,r) not in resources:
                resources.add((q,r))

    def plan_path_to(target):
        ant["path"] = (a_star(ant["pos"], target, cost) or [])[1:]

    # первый целевой ресурс
    spawn_resources()
    if resources:
        plan_path_to(min(resources,key=lambda p:hex_dist(ant["pos"],p)))

    # ——— главный цикл —————————————————————————
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
                dx,dy=e.pos[0]-m0[0], e.pos[1]-m0[1]
                offset=[o0[0]+dx, o0[1]+dy]

        # тик каждую секунду
        if time.time()-last_tick >= 1.0:
            last_tick = time.time()
            spawn_resources()

            speed = ANT_SPEED
            while speed>0 and ant["path"]:
                nxt = ant["path"][0]
                move_cost = cost.get(nxt, None)
                if move_cost is None or move_cost>speed:
                    break
                ant["pos"] = nxt
                ant["path"].pop(0)
                speed -= move_cost

            # если путь исчерпан
            if not ant["path"]:
                if ant["has"] and ant["pos"]==base:
                    ant["has"]=False
                elif (not ant["has"]) and ant["pos"] in resources:
                    resources.remove(ant["pos"]); ant["has"]=True

                if ant["has"]:
                    plan_path_to(base)
                elif resources:
                    plan_path_to(min(resources,key=lambda p:hex_dist(ant["pos"],p)))

        # — рисование —
        screen.fill(BG)
        for (q,r),t in world.items():
            pygame.draw.polygon(screen,TERRAIN[t][1],hex_pts(*center(q,r)))
            pygame.draw.polygon(screen,GRID,hex_pts(*center(q,r)),1)

        for q,r in resources:
            pygame.draw.circle(screen, RES_CLR, center(q,r), HEX_SIZE//3)

        if ant["path"]:
            pts=[center(*ant["pos"])] + [center(q,r) for q,r in ant["path"]]
            pygame.draw.lines(screen, PATH_CLR, False, pts, 4)

        # ant
        cx,cy=center(*ant["pos"])
        pygame.draw.circle(screen, ANT_CLR, (cx,cy), HEX_SIZE//2)
        if ant["has"]:
            pygame.draw.circle(screen, RES_CLR, (cx+HEX_SIZE//2-6, cy-HEX_SIZE//2+6),6)

        pygame.draw.circle(screen, BASE_CLR, center(*base), HEX_SIZE//2,3)

        hud=font.render(f"res={len(resources)}  carrying={ant['has']}  path_len={len(ant['path'])}",True,(220,220,220))
        screen.blit(hud,(10,10))

        pygame.display.flip()
        clock.tick(FPS)

    pygame.quit(); sys.exit()

if __name__=="__main__":
    main()
