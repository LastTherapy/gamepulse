#!/usr/bin/env python3
# datspulse_viewer.py
# ─────────────────────────────────────────────────────────────────────────────
# Flat-top гекс-карта с туманом памяти, перетаскиванием ЛКМ
# ▸ Полоска HP у каждого муравья
# ▸ Жёлтый кружок — несёт ресурс
# ▸ Дружественные и вражеские муравьи имеют **разные PNG по типам**:
#       ANT_IMG — свои,  ENEMY_ANT_IMG — чужие
# ----------------------------------------------------------------------------

import math, pathlib, json, argparse, pygame
from typing import Dict, Tuple

# ────────── активы ──────────────────────────────────────────────────────────
HEX_SIZE, FPS = 38, 60
ASSETS = pathlib.Path("assets")

HEX_COLOR = {1:(220,210,70), 2:(160,160,160), 3:(139,84,33),
             4:( 71,168,77), 5:( 60,60,60)}

RES_IMG = {1:"apple.png", 2:"bread.png", 3:"nectar.png"}

ANT_IMG = {0:"ant_worker.png", 1:"ant_warrior.png", 2:"ant_scout.png"}
ENEMY_ANT_IMG = {0:"enemy_worker.png", 1:"enemy_warrior.png", 2:"enemy_scout.png"}

MAX_HP = {0:130, 1:180, 2:80}      # по справочнику
BG, GRID, HUD = (25,25,25), (60,60,60), (200,200,200)
FOG_FACTOR = 0.45
HP_W, HP_H = HEX_SIZE, 4
SQRT3 = math.sqrt(3)

# ────────── геометрия ───────────────────────────────────────────────────────
def axial_px(q,r,s=HEX_SIZE): return s*1.5*q, s*SQRT3*(r+q/2)
def hex_pts(cx,cy,s=HEX_SIZE):
    return [(round(cx+s*math.cos(math.radians(a))),
             round(cy+s*math.sin(math.radians(a))))
            for a in range(0,360,60)]
def dim(c,k=FOG_FACTOR): return tuple(int(ci*k) for ci in c)

# ────────── основной класс ──────────────────────────────────────────────────
class ArenaRenderer:
    def __init__(self, screen: pygame.Surface):
        self.screen = screen
        self.font_big  = pygame.font.SysFont("consolas",14)
        self.font_small= pygame.font.SysFont("consolas",12)

        self.res_img   = {k:self._load(RES_IMG[k])        for k in RES_IMG}
        self.ant_img   = {k:self._load(ANT_IMG[k])        for k in ANT_IMG}
        self.enemy_img = {k:self._load(ENEMY_ANT_IMG[k])  for k in ENEMY_ANT_IMG}

        self.state=None; self.known={}
        self.q0=self.r0=None; self.map_px=(0,0); self.offset=[0,0]
        self.drag=False; self.m0=(0,0); self.o0=(0,0)

    def _load(self,fname):       # PNG → Surface нужного размера
        img=pygame.image.load(ASSETS/fname).convert_alpha()
        return pygame.transform.smoothscale(img,(HEX_SIZE*2,HEX_SIZE*2))

    # ─── приём нового JSON --------------------------------------------------
    def set_state(self, js:Dict):
        if not js or js.get("error"): return
        self.state=js
        if not js["map"]: return

        for cell in js["map"]:
            self.known[(cell["q"],cell["r"])] = cell["type"]

        if self.q0 is None:
            qs=[q for q,_ in self.known]; rs=[r for _,r in self.known]
            self.q0,self.r0=min(qs),min(rs)
            w,h=axial_px(max(qs)-self.q0,max(rs)-self.r0)
            self.map_px=(w+HEX_SIZE*2, h+HEX_SIZE*2)
            sw,sh=self.screen.get_size()
            self.offset=[(sw-self.map_px[0])//2, (sh-self.map_px[1])//2]

    # ─── перетаскивание ------------------------------------------------------
    def handle_event(self,e):
        if e.type==pygame.MOUSEBUTTONDOWN and e.button==1:
            self.drag=True; self.m0=e.pos; self.o0=tuple(self.offset)
        elif e.type==pygame.MOUSEBUTTONUP and e.button==1:
            self.drag=False
        elif e.type==pygame.MOUSEMOTION and self.drag:
            dx,dy=e.pos[0]-self.m0[0], e.pos[1]-self.m0[1]
            self.offset=[self.o0[0]+dx, self.o0[1]+dy]
            self._clamp()

    def _clamp(self):
        sw,sh=self.screen.get_size(); w,h=self.map_px
        if w>sw: self.offset[0]=max(min(self.offset[0],0), sw-w)
        if h>sh: self.offset[1]=max(min(self.offset[1],0), sh-h)

    # ─── helpers -------------------------------------------------------------
    def _center(self,q,r): x,y=axial_px(q-self.q0,r-self.r0); return round(x+self.offset[0]),round(y+self.offset[1])
    def _blit_icon(self, img, q,r): self.screen.blit(img,img.get_rect(center=self._center(q,r)))

    def _draw_ant(self, ant:Dict, enemy=False):
        q,r=ant['q'],ant['r']
        t  = ant.get('type',0)
        icon = self.enemy_img[t] if enemy else self.ant_img[t]
        self._blit_icon(icon, q, r)

        cx,cy=self._center(q,r)
        maxhp = MAX_HP.get(t,180)
        ratio = max(0, min(1, ant.get('health',0)/maxhp))
        pygame.draw.rect(self.screen,(100,0,0),(cx-HP_W//2, cy+HEX_SIZE//1.3, HP_W, HP_H))
        pygame.draw.rect(self.screen,(0,200,0),(cx-HP_W//2, cy+HEX_SIZE//1.3, int(HP_W*ratio), HP_H))

        # грузовая точка (показываем и у врагов, если нужно)
        if ant.get('food',{}).get('amount',0)>0:
            pygame.draw.circle(self.screen,(255,215,0),(cx+HEX_SIZE//2-6, cy-HEX_SIZE//2+6),6)

    # ─── draw ---------------------------------------------------------------
    def draw(self):
        self.screen.fill(BG)
        if self.q0 is None:
            self.screen.blit(self.font_big.render("Waiting for first map…",True,HUD),(10,10))
            return
        s=self.state
        vis={(c['q'],c['r']) for c in s['map']} if s else set()

        # туман
        for (q,r),t in self.known.items():
            if (q,r) in vis: continue
            pygame.draw.polygon(self.screen,dim(HEX_COLOR[t]),hex_pts(*self._center(q,r)))
            pygame.draw.polygon(self.screen,GRID,hex_pts(*self._center(q,r)),1)

        if not s: return

        # карта
        for c in s['map']:
            cx,cy=self._center(c['q'],c['r'])
            pygame.draw.polygon(self.screen,HEX_COLOR[c['type']],hex_pts(cx,cy))
            pygame.draw.polygon(self.screen,GRID,hex_pts(cx,cy),1)
            self.screen.blit(self.font_small.render(f"{c['q']},{c['r']}",True,(220,40,40)),
                             (cx-HEX_SIZE*0.8, cy-HEX_SIZE*0.55))

        # муравейник
        for h in s['home']:
            pygame.draw.polygon(self.screen,HEX_COLOR[1],hex_pts(*self._center(h['q'],h['r'])))
        spot=s['spot']; pygame.draw.circle(self.screen,(255,255,0),self._center(spot['q'],spot['r']),HEX_SIZE//2,3)

        # объекты
        for f in s['food']: self._blit_icon(self.res_img[f['type']],f['q'],f['r'])
        for a in s['ants']: self._draw_ant(a, enemy=False)
        for en in s['enemies']: self._draw_ant(en, enemy=True)

        hud=self.font_big.render(f"turn {s['turnNo']}  score {s['score']}  next {s['nextTurnIn']:.1f}s",True,HUD)
        self.screen.blit(hud,(10,10))

# ───────── main демо --------------------------------------------------------
def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--json",default="00142.json")
    parser.add_argument("--fullscreen",action="store_true")
    args=parser.parse_args()

    pygame.init()
    flags=pygame.FULLSCREEN if args.fullscreen else pygame.RESIZABLE
    screen=(pygame.display.set_mode((0,0),flags) if args.fullscreen
            else pygame.display.set_mode((1280,800),flags))
    pygame.display.set_caption("Viewer – friend/enemy icons, HP bars")

    data=json.loads(pathlib.Path(args.json).read_text(encoding="utf-8"))
    rend=ArenaRenderer(screen); rend.set_state(data)

    clock=pygame.time.Clock(); run=True
    while run:
        for e in pygame.event.get():
            if e.type==pygame.QUIT or (e.type==pygame.KEYDOWN and e.key==pygame.K_ESCAPE):
                run=False
            rend.handle_event(e)
        rend.draw(); pygame.display.flip(); clock.tick(FPS)
    pygame.quit()

if __name__=="__main__":
    main()
