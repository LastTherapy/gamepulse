#!/usr/bin/env python3
# bot_with_viewer.py  –  «один шаг – один расчёт»

import threading, time, random, sys, json, requests, pygame, heapq
from datspulse_viewer import ArenaRenderer
from collections import defaultdict

URL   = "https://games-test.datsteam.dev"
TOKEN = "39413815-04e3-4ba6-b21e-ad5c29ca2cee"
H     = {"accept":"application/json","X-Auth-Token":TOKEN}

TICK_SEC   = 2.0          # не дергаем API чаще, чем раз в 2 c
ACID_PEN   = 5
SCOUT_STEP = 4

status_text = "‣ waiting registration…"

# ───────── геометрия ──────────────────────────────────────────────────────
DIRS=[(+1,0),(+1,-1),(0,-1),(-1,0),(-1,+1)]
def hex_dist(a,b):
    aq,ar=a; bq,br=b
    return max(abs(aq-bq),abs(ar-br),abs((aq+ar)-(bq+br)))

def a_star(start,goal,move_cost,penalty,blocked):
    """A* с учётом непроходимых blocked (занятые сейчас клетки)."""
    if move_cost.get(goal) is None or goal in blocked:   # до цели физически нельзя
        return None
    open_q=[(hex_dist(start,goal),0,start)]
    best={start:0}; came={}
    while open_q:
        open_q.sort(key=lambda x:x[0])
        _, g, cur=open_q.pop(0)
        if cur==goal:
            path=[cur]
            while cur in came: cur=came[cur]; path.append(cur)
            return path[::-1]
        for dq,dr in DIRS:
            nxt=(cur[0]+dq,cur[1]+dr)
            if nxt in blocked and nxt!=goal:    # чужой муравей / своя цель
                continue
            mc=move_cost.get(nxt)
            if mc is None: continue
            g2=g+mc+penalty.get(nxt,0)
            if g2<best.get(nxt,1e9):
                best[nxt]=g2; came[nxt]=cur
                heapq.heappush(open_q,(g2+hex_dist(nxt,goal),g2,nxt))
    return None

# ───────── регистрация ────────────────────────────────────────────────────
def wait_register():
    global status_text
    deadline=time.time()+5*60
    while time.time()<deadline:
        r=requests.post(URL+"/api/register",headers=H)
        if r.status_code==200:
            status_text="✓ registered, waiting start…"
            return True
        status_text=f"register {r.status_code}: {r.text.strip()}"
        time.sleep(5)
    status_text="⨯ registration window closed"; return False

# ───────── бот ────────────────────────────────────────────────────────────
def bot(renderer:ArenaRenderer):
    global status_text
    if not wait_register(): sys.exit(1)

    known={},                  # типы клеток
    scout_grid=[]
    last_move=0

    while True:
        arena=requests.get(URL+"/api/arena",headers=H).json()
        renderer.set_state(arena)

        # до старта
        if not arena.get("map"):
            status_text=json.dumps(arena,indent=2,ensure_ascii=False)
            time.sleep(2); continue

        status_text=f"turn {arena['turnNo']:>4}  ants:{len(arena['ants'])}  food:{len(arena['food'])}"

        # --- карта
        for c in arena["map"]:
            known[c["q"],c["r"]]=c["type"]

        move_cost={(q,r):(2 if t==3 else 1) if t!=5 else None
                   for (q,r),t in known.items()}
        penalty  ={(q,r):ACID_PEN if t==4 else 0
                   for (q,r),t in known.items()}

        # --- вспомогательные наборы
        spot=(arena["spot"]["q"],arena["spot"]["r"])
        helpers=[(h["q"],h["r"]) for h in arena["home"]
                 if (h["q"],h["r"])!=spot]
        resources=[(f["q"],f["r"]) for f in arena["food"]]

        if not scout_grid:                      # однажды строим точки обзора
            rng=range(-SCOUT_STEP*4,SCOUT_STEP*4+1)
            for dq in rng:
                for dr in rng:
                    if dq%SCOUT_STEP==dr%SCOUT_STEP==0:
                        cell=(spot[0]+dq, spot[1]+dr)
                        if known.get(cell,5)!=5:
                            scout_grid.append(cell)

        # --- пауза, чтобы не спамить
        if time.time()-last_move < TICK_SEC:
            time.sleep(0.2); continue
        last_move=time.time()

        occupied={(a["q"],a["r"]) for a in arena["ants"]}

        # шаги, выбранные прямо сейчас (чтобы два не лезли в одно)
        reservation=set()
        decisions=[]      # (ant_id, step_qr)

        for ant in arena["ants"]:
            aid=ant["id"]
            pos=(ant["q"],ant["r"])
            typ=ant["type"]
            carrying=ant["food"]["amount"]>0

            # --- выбор цели
            if typ==2:                        # разведчики
                target=min(scout_grid, key=lambda c:hex_dist(pos,c))
            elif carrying:
                target=min(helpers, key=lambda h:hex_dist(pos,h))
            elif resources:
                target=min(resources, key=lambda r:hex_dist(pos,r))
            else:
                dq,dr=random.choice(DIRS); target=(pos[0]+dq,pos[1]+dr)

            # --- ищем путь А* (понимая, что occupied – стены на этот тик)
            path=a_star(pos, target, move_cost, penalty, occupied)
            if not path or len(path)==1:      # стоим
                step=pos
            else:
                step=path[1]

            # если уже кто-то зарезервировал эту клетку – уступаем (стоим)
            if step in reservation:
                step=pos
            reservation.add(step)
            decisions.append((aid, step))

        # --- формируем JSON move
        moves=[{"ant":aid,"path":[{"q":q,"r":r}]} for aid,(q,r) in decisions]
        requests.post(URL+"/api/move",headers=H,json={"moves":moves})

# ───────── окно ────────────────────────────────────────────────────────────
def main():
    global status_text
    pygame.init()
    screen=pygame.display.set_mode((1280,800),pygame.RESIZABLE)
    pygame.display.set_caption("Datspulse bot – single-step planner")
    renderer=ArenaRenderer(screen)
    font=pygame.font.SysFont("consolas",14)

    threading.Thread(target=bot,args=(renderer,),daemon=True).start()

    clock=pygame.time.Clock(); running=True
    while running:
        for e in pygame.event.get():
            if e.type==pygame.QUIT or (e.type==pygame.KEYDOWN and e.key==pygame.K_ESCAPE):
                running=False
            renderer.handle_event(e)

        renderer.draw()
        y=10
        for line in status_text.splitlines():
            screen.blit(font.render(line,True,(255,255,0)),(10,y)); y+=16
        pygame.display.flip(); clock.tick(60)
    pygame.quit()

if __name__=="__main__":
    main()
