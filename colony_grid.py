#!/usr/bin/env python3
# colony_grid.py
# ─────────────────────────────────────────────────────────────────────────────
# Демонстрационная логика “рабочие-сборщики + строй 4×4”.
#
# • Карта 20×20, типы гексов как прежде (камни – стены, кислота – проходима,
#   но штраф в A*).
# • Дом = три гекса (spot + 2 вспомогательных).  Рабочие выгружают НЕКТАР
#   на ВСПОМОГАТЕЛЬНЫЕ клетки, а не на spot.
# • Каждую секунду:
#     1. В доме появляется по **одному новому рабочему** (до 16 всего).
#     2. Появляются случайные ресурсы.
#     3. Каждому рабочему выбирается задача:
#         – если несёт ресурс → вернуться на ближайший *вспомогательный*
#           гекс дома;
#         – иначе ближайший ресурс;
#         – если ресурсов нет → занять свободную ячейку 4 × 4-сетки
#           вокруг дома (патруль);
#     4. За тик рабочий тратит до 4 ОП, учитывая стоимость клетки.
#
# Управление визуализацией:
#     • Левый клик – перетаскивание карты.
#     • Esc / крестик окна – выход.
# ----------------------------------------------------------------------------

import math, random, time, sys, pygame
from typing import Dict, Tuple, List, Set, Optional

# ───────── константы ────────────────────────────────────────────────────────
HEX_SIZE            = 26
GRID_W, GRID_H      = 20, 20
FPS                 = 60
TICK_SEC            = 1.0
SPAWN_CHANCE        = 0.13
MAX_RES             = 60
MAX_WORKERS         = 16
WORKER_SPEED        = 4

TERRAIN = {                         # name,         rgb,      move, pen
    2: ("empty", (170,170,170), 1, 0),
    3: ("dirt",  (139, 84, 33), 2, 0),
    4: ("acid",  ( 20,170,230), 1, 5),   # избегаем, но проходим
    5: ("stone", ( 60, 60, 60), None, None),   # стена
}

RES_CLR = (255,215,0)
WORK_CLR= (255,140,0)
PATH_CLR= (220,40,40)
HOME_CLR= (255,255,0)
BG, GRID = (25,25,25), (60,60,60)
SQRT3    = math.sqrt(3)

# ───────── геометрия ────────────────────────────────────────────────────────
DIRS = [(+1,0),(+1,-1),(0,-1),(-1,0),(-1,+1),(0,+1)]
def axial_px(q,r,s=HEX_SIZE): return s*1.5*q, s*SQRT3*(r+q/2)
def hex_pts(cx,cy,s=HEX_SIZE):
    return [(round(cx+s*math.cos(math.radians(a))),
             round(cy+s*math.sin(math.radians(a))))
            for a in range(0,360,60)]
def hex_dist(a,b):
    aq,ar=a; bq,br=b
    return max(abs(aq-bq),abs(ar-br),abs((aq+ar)-(bq+br)))

# ───────── A* (move_cost+penalty) ───────────────────────────────────────────
def a_star(start,goal,move_cost,penalty):
    if move_cost.get(goal) is None: return None
    open_l=[(hex_dist(start,goal),0,start)]
    best={start:0}; came={}
    while open_l:
        open_l.sort(key=lambda x:x[0])
        _, gpen, cur=open_l.pop(0)
        if cur==goal:
            path=[cur]
            while cur in came: cur=came[cur]; path.append(cur)
            return path[::-1]
        for dq,dr in DIRS:
            nxt=(cur[0]+dq,cur[1]+dr)
            mv=move_cost.get(nxt)
            if mv is None: continue
            g2=gpen+mv+penalty.get(nxt,0)
            if g2<best.get(nxt,1e9):
                best[nxt]=g2; came[nxt]=cur
                f=g2+hex_dist(nxt,goal)
                open_l.append((f,gpen+mv,nxt))
    return None

# ───────── генерация карты ─────────────────────────────────────────────────
def make_map():
    mp={}
    for q in range(GRID_W):
        for r in range(GRID_H):
            mp[(q,r)] = random.choices([2,3,4,5],[70,15,10,5])[0]
    return mp

def random_free(world, taken:Set):
    while True:
        p=(random.randrange(GRID_W), random.randrange(GRID_H))
        if world[p]!=5 and p not in taken: return p

# ───────── визуализация вспомогательная ────────────────────────────────────
def draw_hex(screen, color, cx, cy):
    pygame.draw.polygon(screen, color, hex_pts(cx,cy))
    pygame.draw.polygon(screen, GRID,  hex_pts(cx,cy),1)

# ───────── main ────────────────────────────────────────────────────────────
def main():
    pygame.init()
    screen=pygame.display.set_mode((1200,900), pygame.RESIZABLE)
    pygame.display.set_caption("Colony with 4×4 grid & return logic")

    # карта и базовые структуры
    world = make_map()
    move_cost={pos:TERRAIN[t][2] for pos,t in world.items()}
    penalty  ={pos:TERRAIN[t][3] for pos,t in world.items()}
    home_spot=(GRID_W//2, GRID_H//2)
    home_cells=[home_spot, (home_spot[0]-1,home_spot[1]),
                            (home_spot[0],home_spot[1]-1)]   # helper cells

    workers:List[Dict] = []        # каждый: pos, carrying, path, target
    resources:Set=set()
    offset=[150,150]; drag=False; m0=(0,0); o0=(0,0)
    clock=pygame.time.Clock(); last_tick=time.time()
    font=pygame.font.SysFont("consolas",14)

    # ─── helpers -----------------------------------------------------------
    def center(q,r): x,y=axial_px(q,r); return round(x+offset[0]), round(y+offset[1])

    def spawn_resources():
        if len(resources)>=MAX_RES: return
        for (q,r),t in world.items():
            if t==5 or (q,r) in resources: continue
            if random.random()<SPAWN_CHANCE and (q,r) not in {w['pos'] for w in workers}:
                resources.add((q,r))

    def spawn_worker():
        if len(workers)>=MAX_WORKERS: return
        workers.append({"pos":home_spot, "carrying":False, "path":[], "target":None})

    grid_offsets=[(dq,dr) for dq in range(-2,2) for dr in range(-2,2)]  # 4×4

    def choose_grid_target(wpos):
        # ближайший свободный offset
        taken={tuple(w['target']) for w in workers if w['target'] and not w['carrying']}
        for dq,dr in sorted(grid_offsets, key=lambda p:hex_dist((0,0),p)):
            cell=(home_spot[0]+dq, home_spot[1]+dr)
            if world.get(cell,5)==5: continue
            if cell in taken: continue
            return cell
        return None

    def plan(worker, goal):
        path=a_star(worker["pos"], goal, move_cost, penalty)
        worker["path"]=path[1:] if path else []
        worker["target"]=goal

    # ─── цикл ----------------------------------------------------------------
    running=True
    while running:
        # events
        for e in pygame.event.get():
            if e.type==pygame.QUIT or (e.type==pygame.KEYDOWN and e.key==pygame.K_ESCAPE):
                running=False
            elif e.type==pygame.MOUSEBUTTONDOWN and e.button==1:
                drag=True; m0=e.pos; o0=tuple(offset)
            elif e.type==pygame.MOUSEBUTTONUP and e.button==1:
                drag=False
            elif e.type==pygame.MOUSEMOTION and drag:
                dx,dy=e.pos[0]-m0[0], e.pos[1]-m0[1]; offset=[o0[0]+dx,o0[1]+dy]

        # тик
        if time.time()-last_tick>=TICK_SEC:
            last_tick=time.time()
            spawn_resources(); spawn_worker()

            # обновить penalty (динамика не нужна — нет врагов двигающихся)

            for w in workers:
                speed=WORKER_SPEED
                while speed>0 and w["path"]:
                    nxt=w["path"][0]; mv=move_cost[nxt]
                    if mv is None or mv>speed: break
                    w["pos"]=nxt; w["path"].pop(0); speed-=mv

                # достиг цели?
                if not w["path"]:
                    if w["carrying"] and w["pos"] in home_cells[1:]:
                        w["carrying"]=False
                    elif (not w["carrying"]) and w["pos"] in resources:
                        resources.remove(w["pos"]); w["carrying"]=True

                    # выбрать новую цель
                    if w["carrying"]:
                        plan(w, random.choice(home_cells[1:]))
                    elif resources:
                        nearest=min(resources, key=lambda p:hex_dist(w["pos"],p))
                        plan(w, nearest)
                    else:
                        grid_t=choose_grid_target(w["pos"])
                        if grid_t: plan(w, grid_t)

        # ─── рисование -----------------------------------------------------
        screen.fill(BG)
        for (q,r),t in world.items():
            draw_hex(screen,TERRAIN[t][1],*center(q,r))

        # ресурсы
        for rq,rr in resources:
            pygame.draw.circle(screen, RES_CLR, center(rq,rr), HEX_SIZE//3)

        # home
        for h in home_cells[1:]:
            pygame.draw.circle(screen, HOME_CLR, center(*h), HEX_SIZE//2,2)
        pygame.draw.circle(screen,(255,255,255), center(*home_spot), HEX_SIZE//2,2)

        # paths
        for w in workers:
            if w["path"]:
                pts=[center(*w["pos"])] + [center(q,r) for q,r in w["path"]]
                pygame.draw.lines(screen, PATH_CLR, False, pts, 3)

        # workers
        for w in workers:
            cx,cy=center(*w["pos"])
            pygame.draw.circle(screen, WORK_CLR, (cx,cy), HEX_SIZE//2)
            if w["carrying"]:
                pygame.draw.circle(screen, RES_CLR,(cx+HEX_SIZE//2-6, cy-HEX_SIZE//2+6),6)

        hud=font.render(f"workers={len(workers)} res={len(resources)}",True,(220,220,220))
        screen.blit(hud,(10,10))

        pygame.display.flip()
        clock.tick(FPS)

    pygame.quit(); sys.exit()

if __name__=="__main__":
    main()
