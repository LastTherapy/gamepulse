#!/usr/bin/env python3
# path_demo.py  —  случайная 20×20 карта, ПКМ-указание цели, визуальный путь

import math, random, pygame, sys
from typing import Dict, Tuple, List

# ────────── ПАРАМЕТРЫ ──────────────────────────────────────────────────────
HEX_SIZE = 28
GRID_W, GRID_H = 20, 20               # 20×20 гексов
FPS     = 60

TERRAIN = {
    2: ("empty",  (170,170,170),  1),   # type -> (name, color, cost)
    3: ("dirt",   (139, 84, 33),  2),
    4: ("acid",   ( 20,170,230), 15),
    5: ("stone",  ( 60, 60, 60), None)  # None cost = стена
}
BG, GRID = (25,25,25), (60,60,60)
ANT_CLR  = (255,140,0)
PATH_CLR = (220,40,40)

SQRT3 = math.sqrt(3)

# ────────── Гекс-математика (flat-top) ─────────────────────────────────────
DIRS = [(+1,0),(+1,-1),(0,-1),(-1,0),(-1,+1),(0,+1)]

def axial_px(q:int,r:int,s=HEX_SIZE):  return s*1.5*q, s*SQRT3*(r+q/2)
def hex_pts(cx,cy,s=HEX_SIZE):
    return [(round(cx+s*math.cos(math.radians(a))),
             round(cy+s*math.sin(math.radians(a)))) for a in range(0,360,60)]
def hex_dist(a,b):
    aq,ar=a; bq,br=b
    return max(abs(aq-bq),abs(ar-br),abs((aq+ar)-(bq+br)))

# ────────── A* поиск ───────────────────────────────────────────────────────
def a_star(start,goal,cost_of):
    open_h=[(hex_dist(start,goal),0,start)]
    g={start:0}; came={}
    while open_h:
        _,gcur,cur=open_h.pop(0)
        if cur==goal:
            path=[cur];  # восстанавливаем
            while cur in came: cur=came[cur]; path.append(cur)
            return path[::-1]
        for dq,dr in DIRS:
            nxt=(cur[0]+dq,cur[1]+dr)
            c=cost_of.get(nxt)
            if c is None: continue
            g2=gcur+c
            if g2<g.get(nxt,1e9):
                came[nxt]=cur; g[nxt]=g2
                f=g2+hex_dist(nxt,goal)
                # вставляем упорядоченно (простая очередь вместо heap — карта маленькая)
                idx=0
                while idx<len(open_h) and open_h[idx][0]<f: idx+=1
                open_h.insert(idx,(f,g2,nxt))
    return None

# ────────── Генерация карты -------------------------------------------------
def make_map():
    mp={}
    for q in range(GRID_W):
        for r in range(GRID_H):
            t=random.choices([2,3,4,5],[70,15,10,5])[0]
            mp[(q,r)] = t
    return mp

# ────────── Main ------------------------------------------------------------
def main():
    pygame.init()
    screen=pygame.display.set_mode((1200,900), pygame.RESIZABLE)
    pygame.display.set_caption("Right-click: find path")

    # карта и муравей
    world = make_map()
    ant = (GRID_W//2, GRID_H//2)
    target:Tuple[int,int]|None = None
    path:List[Tuple[int,int]]|None = None

    font = pygame.font.SysFont("consolas", 14)
    offset=[100,100]; drag=False; m0=(0,0); o0=(0,0)
    clock=pygame.time.Clock(); run=True

    # словарь стоимость
    cost = {pos:(TERRAIN[t][2]) for pos,t in world.items()}

    def center(q,r): x,y=axial_px(q,r); return round(x+offset[0]), round(y+offset[1])

    while run:
        for e in pygame.event.get():
            if e.type==pygame.QUIT or (e.type==pygame.KEYDOWN and e.key==pygame.K_ESCAPE):
                run=False
            elif e.type==pygame.MOUSEBUTTONDOWN and e.button==1:
                drag=True; m0=e.pos; o0=tuple(offset)
            elif e.type==pygame.MOUSEBUTTONUP and e.button==1:
                drag=False
            elif e.type==pygame.MOUSEMOTION and drag:
                dx,dy=e.pos[0]-m0[0], e.pos[1]-m0[1]
                offset=[o0[0]+dx, o0[1]+dy]
            elif e.type==pygame.MOUSEBUTTONDOWN and e.button==3:
                # ПКМ: выбираем гекс
                mx,my=e.pos
                # пиксели -> axial (обратная формула flat-top)
                mx-=offset[0]; my-=offset[1]
                q = round((2/3)*mx/HEX_SIZE)
                r = round((-q/2) + my/(SQRT3*HEX_SIZE))
                target=(q,r)
                if target in world:                     # внутри поля
                    path = a_star(ant, target, cost)
                else:
                    path=None

        screen.fill(BG)

        # гексы
        for (q,r),typ in world.items():
            cx,cy=center(q,r)
            pygame.draw.polygon(screen, TERRAIN[typ][1], hex_pts(cx,cy))
            pygame.draw.polygon(screen, GRID, hex_pts(cx,cy),1)

        # путь
        if path:
            pts=[center(q,r) for q,r in path]
            pygame.draw.lines(screen, PATH_CLR, False, pts, 4)

        # ant & target mark
        pygame.draw.circle(screen, ANT_CLR, center(*ant), HEX_SIZE//2, 0)
        if target:
            pygame.draw.circle(screen, (255,255,0), center(*target), HEX_SIZE//2,3)

        # HUD
        hud = font.render(f"LMB drag | RMB path | len={len(path) if path else '–'}",True,(220,220,220))
        screen.blit(hud,(10,10))

        pygame.display.flip()
        clock.tick(FPS)

    pygame.quit()
    sys.exit()

if __name__=="__main__":
    main()
