#!/usr/bin/env python3
# bot_with_viewer.py  —  вывод JSON-ответа прямо в окне

import threading, time, heapq, random, sys, json, requests, pygame
from collections import defaultdict
from datspulse_viewer import ArenaRenderer

# ───────── API / параметры ─────────────────────────────────────────────────
URL   = "https://games-test.datsteam.dev"
TOKEN = "39413815-04e3-4ba6-b21e-ad5c29ca2cee"
H     = {"accept":"application/json","X-Auth-Token":TOKEN}

TICK_SEC   = 2.0
ACID_PEN   = 5
SCOUT_STEP = 4

# ───────── глобальный статус для вывода ------------------------------------
status_text = "‣ waiting registration…"       # будет обновляться из bot-потока

# ───────── геометрия / A* (как ранее) --------------------------------------
DIRS=[(+1,0),(+1,-1),(0,-1),(-1,0),(-1,+1)]
def hex_dist(a,b):
    aq,ar=a; bq,br=b
    return max(abs(aq-bq),abs(ar-br),abs((aq+ar)-(bq+br)))
def a_star(start,goal,move,pen):
    if move.get(goal) is None: return None
    open_h=[(hex_dist(start,goal),0,start)]; best={start:0}; came={}
    while open_h:
        open_h.sort(key=lambda x:x[0]); _,g,cur=open_h.pop(0)
        if cur==goal:
            path=[cur]
            while cur in came: cur=came[cur]; path.append(cur)
            return path[::-1]
        for dq,dr in DIRS:
            nxt=(cur[0]+dq,cur[1]+dr); mv=move.get(nxt)
            if mv is None: continue
            g2=g+mv+pen.get(nxt,0)
            if g2<best.get(nxt,1e9):
                best[nxt]=g2; came[nxt]=cur
                open_h.append((g2+hex_dist(nxt,goal),g2,nxt))
    return None

# ───────── регистрация (≤5 мин) -------------------------------------------
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

# ───────── бот-поток -------------------------------------------------------
def bot(renderer:ArenaRenderer):
    global status_text
    if not wait_register(): sys.exit(1)

    known={}; mem_path=defaultdict(list); scout_grid=[]
    last_move=0.0

    while True:
        arena=requests.get(URL+"/api/arena",headers=H).json()
        renderer.set_state(arena)

        # до старта: показываем сырой JSON
        if not arena.get("map"):
            status_text=json.dumps(arena,indent=2,ensure_ascii=False)
            time.sleep(2); continue

        # после старта: краткая строка
        status_text=f"turn {arena['turnNo']}  ants:{len(arena['ants'])}  food:{len(arena['food'])}"

        for c in arena["map"]: known[(c["q"],c["r"])]=c["type"]
        move={p:(2 if t==3 else 1) if t!=5 else None for p,t in known.items()}
        pen ={p:ACID_PEN if t==4 else 0 for p,t in known.items()}

        spot=(arena["spot"]["q"],arena["spot"]["r"])
        helpers=[(h["q"],h["r"]) for h in arena["home"] if (h["q"],h["r"])!=spot]
        resources=[(f["q"],f["r"]) for f in arena["food"]]

        if not scout_grid:
            for dq in range(-SCOUT_STEP*4,SCOUT_STEP*4):
                for dr in range(-SCOUT_STEP*4,SCOUT_STEP*4):
                    if dq%SCOUT_STEP==0 and dr%SCOUT_STEP==0:
                        cell=(spot[0]+dq,spot[1]+dr)
                        if known.get(cell,5)!=5: scout_grid.append(cell)

        if time.time()-last_move < TICK_SEC:
            time.sleep(0.2); continue
        last_move=time.time()

        moves=[]
        for ant in arena["ants"]:
            aid=ant["id"]; typ=ant["type"]; pos=(ant["q"],ant["r"])
            carrying=ant["food"]["amount"]>0; path=mem_path[aid]

            if not path:
                if typ==2:
                    target=min(scout_grid,key=lambda c:hex_dist(pos,c))
                elif carrying:
                    target=min(helpers,key=lambda h:hex_dist(pos,h))
                elif resources:
                    target=min(resources,key=lambda r:hex_dist(pos,r))
                else:
                    dq,dr=random.choice(DIRS); target=(pos[0]+dq,pos[1]+dr)
                calc=a_star(pos,target,move,pen) or [pos,target]
                mem_path[aid]=calc[1:]

            step=mem_path[aid].pop(0) if mem_path[aid] else pos
            moves.append({"ant":aid,"path":[{"q":step[0],"r":step[1]}]})

        requests.post(URL+"/api/move",headers=H,json={"moves":moves})

# ───────── главное окно -----------------------------------------------------
def main():
    global status_text
    pygame.init()
    screen=pygame.display.set_mode((1280,800),pygame.RESIZABLE)
    pygame.display.set_caption("Datspulse bot – live JSON on screen")
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

        # ---- вывод текста поверх ----
        y=10
        for line in status_text.splitlines():
            surf=font.render(line[:120],True,(255,255,0))
            screen.blit(surf,(10,y)); y+=16

        pygame.display.flip(); clock.tick(60)
    pygame.quit()

if __name__=="__main__":
    main()
