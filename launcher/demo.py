# Orbitals PC Recomp, a work based on SwitchRecomp by MZ Labs. GNU AGPL v3.0 with the additional terms of NOTICE.txt (LICENSE.txt).
"""The screens shown while the launcher works for a long time, small demos in the spirit of the 90s demoscene, one per task:

- "code" (recompiling the game): a listing of ARM64 instructions turning into C scrolls like a cracktro's code view, a vector
  wireframe turns beside it;
- "shader" (preparing the shaders): a plasma, the classic per-pixel effect, under a rotating ball of shaded dots;
- "stars" (downloads, data): a starfield flying forward behind copper bars.

All share the title, a sine scroller with the credits, a segmented bar with the real progress and the step. Plain Tk canvas items
moved about 30 times a second: next to nothing beside the compilers and translators running at the same time."""
import math
import random
import tkinter as tk
from tkinter import font

from .look import px

BG = "#07060f"
NEON = ("#3ee8ff", "#ff3ea5", "#ffb13d", "#8f6bff")
SCROLL = ("      LIFTOFF  //  ORBITALS PC RECOMP  //  NATIVE PC PORT BY STATIC RECOMPILATION  //  BUILT ON SWITCHRECOMP BY MZ LABS  //  "
          "YOUR OWN COPY, RECOMPILED ON YOUR OWN MACHINE  //  NVN2 TO VULKAN, SHADERS TO SPIR-V  //  "
          "GREETINGS TO EVERY PLAYER TESTING THIS PREVIEW  //  GRAB A FRIEND AND A SECOND CONTROLLER  //  ")
FRAME_MS = 33
STYLES = ("code", "shader", "stars")
# what the recompiler does, as a listing: the ARM64 instruction and the C it becomes (illustrative, not the game's code)
LISTING = (("stp x29, x30, [sp, #-0x20]!", "MEM64(sp - 0x20) = x[29]; MEM64(sp - 0x18) = x[30];"),
           ("mov x29, sp", "x[29] = sp;"),
           ("ldr w8, [x0, #0x48]", "x[8] = MEM32(x[0] + 0x48);"),
           ("cmp w8, #0x3", "nzcv = sub_flags32(x[8], 3);"),
           ("b.ne 0x710023a4c0", "if (!Z) goto L_710023a4c0;"),
           ("fmul s0, s1, s2", "v[0].s = v[1].s * v[2].s;"),
           ("fadd s0, s0, s3", "v[0].s = v[0].s + v[3].s;"),
           ("bl 0x7100c81e30", "fn_7100c81e30(ctx);"),
           ("ldp x29, x30, [sp], #0x20", "x[29] = MEM64(sp); x[30] = MEM64(sp + 8);"),
           ("ret", "return;"),
           ("adrp x9, 0x7102f6c000", "x[9] = 0x7102f6c000;"),
           ("add x9, x9, #0x5d8", "x[9] += 0x5d8;"),
           ("csel w0, w8, wzr, gt", "x[0] = GT ? (u32)x[8] : 0;"),
           ("ldaxr w10, [x9]", "x[10] = atomic_load_acq32(x[9]);"),
           ("stlxr w11, w12, [x9]", "x[11] = !atomic_cas_rel32(x[9], x[10], x[12]);"),
           ("cbnz w11, 0x7100a3f0c8", "if (x[11]) goto L_7100a3f0c8;"))


def _mix(a, b, t):
    """the colour between a and b (#rrggbb) at t in [0, 1]"""
    pa = [int(a[i:i + 2], 16) for i in (1, 3, 5)]; pb = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(pa, pb))


def style_for(title):
    """The demo of a task from its title (ui.py: RECOMPILING ORBITALS, PREPARING SHADERS, DOWNLOADING UPDATE…)."""
    title = (title or "").upper()
    return "code" if "RECOMPIL" in title else "shader" if "SHADER" in title else "stars"


class DemoScreen(tk.Canvas):
    """A canvas that animates itself while it is mapped; set_progress(fraction, step, detail) updates the bar and the texts."""

    def __init__(self, parent, title="", style=None, height=420, **options):
        super().__init__(parent, bg=BG, highlightthickness=0, height=height, **options)
        families = set(font.families())
        mono = next((f for f in ("Consolas", "DejaVu Sans Mono", "Liberation Mono", "Courier New") if f in families), "TkFixedFont")
        self.f_title = (mono, 20, "bold"); self.f_scroll = (mono, 17, "bold"); self.f_text = (mono, 10); self.f_code = (mono, 9)
        self.title = title
        self.style = style if style in STYLES else style_for(title)
        self.fraction = 0.0; self.step = ""; self.detail = ""
        self.t = 0; self.running = False; self.items_ready = False
        self.bind("<Configure>", lambda _e: self._layout())
        self.bind("<Map>", lambda _e: self.start())
        self.bind("<Unmap>", lambda _e: self.stop())
        self.bind("<Destroy>", lambda _e: self.stop())

    # ---- public ----
    def set_progress(self, fraction=None, step=None, detail=None):
        if fraction is not None: self.fraction = max(0.0, min(1.0, fraction))
        if step is not None: self.step = step
        if detail is not None: self.detail = detail

    def start(self):
        if not self.running:
            self.running = True
            self.after(FRAME_MS, self._tick)

    def stop(self):
        self.running = False

    # ---- layout ----
    def _layout(self):
        self.delete("all")
        w, h = max(self.winfo_width(), 200), max(self.winfo_height(), 200)
        self.w, self.h = w, h
        getattr(self, "_layout_" + self.style)(w, h)
        title_y = h * 0.12 if self.style != "stars" else h * 0.17
        self.title_shadow = self.create_text(w / 2 + px(3), title_y + px(3), text=self.title, font=self.f_title, fill="#2a0c3a")
        self.title_item = self.create_text(w / 2, title_y, text=self.title, font=self.f_title, fill=NEON[0])
        # sine scroller: one text item per visible character
        self.char_w = font.Font(font=self.f_scroll).measure("M")
        self.scroll_items = [self.create_text(0, 0, text="", font=self.f_scroll, fill=NEON[2], anchor="w")
                             for _ in range(int(w / self.char_w) + 3)]
        # segmented progress bar on a dark band, readable over any background
        self.seg_n = 40; bar_w = min(w - px(60), px(640)); self.bar_x = (w - bar_w) / 2; self.bar_y = h * 0.76; self.seg_w = bar_w / self.seg_n
        self.create_rectangle(0, self.bar_y - px(14), w, h, fill=BG, outline="")
        self.create_rectangle(self.bar_x - 4, self.bar_y - 4, self.bar_x + bar_w + 4, self.bar_y + px(18) + 4, outline=NEON[0], width=1)
        self.segs = [self.create_rectangle(self.bar_x + i * self.seg_w + 1, self.bar_y, self.bar_x + (i + 1) * self.seg_w - 2, self.bar_y + px(18),
                                           fill="#141226", outline="") for i in range(self.seg_n)]
        self.pct_item = self.create_text(w / 2, self.bar_y + px(40), text="", font=self.f_text, fill="#e8e6ff")
        self.detail_item = self.create_text(w / 2, self.bar_y + px(60), text="", font=self.f_text, fill="#8e8aa8", width=w - px(40))
        for y in range(0, h, 3):   # scanlines
            self.create_line(0, y, w, y, fill="#000000", stipple="gray25")
        self.items_ready = True

    def _layout_stars(self, w, h):
        rnd = random.Random(7)
        self.stars = [[rnd.uniform(-1, 1), rnd.uniform(-1, 1), rnd.uniform(0.05, 1), 0] for _ in range(140)]
        for s in self.stars:
            s[3] = self.create_oval(0, 0, 0, 0, fill="#ffffff", outline="")
        self.bars = []   # copper bars: stacks of thin rectangles, dark at the edges and bright in the middle
        for k, colour in enumerate(NEON):
            rows = [self.create_rectangle(0, 0, w, 0, fill=_mix(BG, colour, math.sin(math.pi * (i + 0.5) / 14) ** 1.5), outline="")
                    for i in range(14)]
            self.bars.append((k, rows))

    def _layout_code(self, w, h):
        self.code_h = font.Font(font=self.f_code).metrics("linespace") + 2
        self.code_top, self.code_bottom = h * 0.20, h * 0.58
        n = int((self.code_bottom - self.code_top) / self.code_h) + 2
        self.code_rows = [(self.create_text(24, 0, text="", font=self.f_code, fill="#2f8f5f", anchor="w"),
                           self.create_text(24 + w * 0.30, 0, text="", font=self.f_code, fill="#4fd0a0", anchor="w")) for _ in range(n)]
        self.create_rectangle(0, self.code_top - px(30), w * 0.66, self.code_top - 2, fill=BG, outline="")   # the listing scrolls under the title
        # a wireframe: an icosahedron, the vector object of the era
        g = (1 + 5 ** 0.5) / 2
        self.verts = [(-1, g, 0), (1, g, 0), (-1, -g, 0), (1, -g, 0), (0, -1, g), (0, 1, g), (0, -1, -g), (0, 1, -g),
                      (g, 0, -1), (g, 0, 1), (-g, 0, -1), (-g, 0, 1)]
        self.edges = [(a, b) for a in range(12) for b in range(a + 1, 12)
                      if abs(sum((self.verts[a][i] - self.verts[b][i]) ** 2 for i in range(3)) - 4) < 1e-6]
        self.edge_items = [self.create_line(0, 0, 0, 0, fill=NEON[0], width=2) for _ in self.edges]

    def _layout_shader(self, w, h):
        self.cols, self.rows = 32, 14
        self.cell_w, self.cell_h = w / self.cols, (h * 0.62) / self.rows
        self.plasma_top = h * 0.06
        self.cells = [[self.create_rectangle(c * self.cell_w, self.plasma_top + r * self.cell_h, (c + 1) * self.cell_w + 1,
                                             self.plasma_top + (r + 1) * self.cell_h + 1, fill=BG, outline="")
                       for c in range(self.cols)] for r in range(self.rows)]
        stops = ("#120634", NEON[3], NEON[1], NEON[2], NEON[0], "#120634")   # night, violet, pink, gold, cyan, back to night
        self.palette = []
        for i in range(64):
            x = i / 64 * (len(stops) - 1); k = int(x)
            self.palette.append(_mix(BG, _mix(stops[k], stops[k + 1], x - k), 0.5))   # dimmed, so the texts stay readable
        rnd = random.Random(5)   # a ball of dots, a Fibonacci sphere
        n = 90
        self.ball = [(math.cos(math.tau * i / g) * math.sqrt(1 - (1 - 2 * (i + 0.5) / n) ** 2), 1 - 2 * (i + 0.5) / n,
                      math.sin(math.tau * i / g) * math.sqrt(1 - (1 - 2 * (i + 0.5) / n) ** 2))
                     for i, g in ((i, (1 + 5 ** 0.5) / 2) for i in range(n))]
        self.ball_items = [self.create_oval(0, 0, 0, 0, fill="#ffffff", outline="") for _ in self.ball]
        rnd.shuffle(self.ball_items)

    # ---- frames ----
    def _tick(self):
        if not self.running:
            return
        if not self.items_ready:
            self._layout()
        try:
            getattr(self, "_frame_" + self.style)()
            self._frame_common()
        except tk.TclError:
            self.running = False
            return
        self.t += 1
        self.after(FRAME_MS, self._tick)

    def _frame_stars(self):
        w, h, t = self.w, self.h, self.t
        cx, cy = w / 2, h * 0.45
        for s in self.stars:   # 3D starfield, flying forward
            s[2] -= 0.012
            if s[2] <= 0.04: s[0], s[1], s[2] = random.uniform(-1, 1), random.uniform(-1, 1), 1.0
            x, y = cx + s[0] / s[2] * w * 0.35, cy + s[1] / s[2] * h * 0.35
            r = max(0.6, 2.2 * (1 - s[2]))
            self.coords(s[3], x - r, y - r, x + r, y + r)
            self.itemconfigure(s[3], fill=_mix("#1a1840", "#ffffff", 1 - s[2]))
        for k, rows in self.bars:   # copper bars swinging behind the title
            y0 = h * 0.17 + math.sin(t * 0.045 + k * 0.9) * h * 0.11 - 7 * 3
            for i, item in enumerate(rows):
                self.coords(item, 0, y0 + i * 3, w, y0 + i * 3 + 3)

    def _frame_code(self):
        w, h, t = self.w, self.h, self.t
        scroll = t * 1.2   # the listing scrolls up, one address per line
        first = int(scroll // self.code_h); sub = scroll % self.code_h
        for i, (asm_item, c_item) in enumerate(self.code_rows):
            n = first + i
            asm, c = LISTING[n % len(LISTING)]
            y = self.code_top + i * self.code_h - sub
            addr = 0x7100a3f000 + n * 4
            fade = max(0.0, min(1.0, (y - self.code_top) / 40, (self.code_bottom - y) / 40))
            self.coords(asm_item, 24, y); self.coords(c_item, 24 + w * 0.30, y)
            self.itemconfigure(asm_item, text=f"{addr:010x}  {asm}", fill=_mix(BG, "#3fa070", fade))
            self.itemconfigure(c_item, text=f"→ {c}", fill=_mix(BG, "#6ff0b8", fade))
        cx, cy, r = w * 0.82, h * 0.43, min(w, h) * 0.15   # the wireframe turning
        a, b = t * 0.03, t * 0.021
        pts = []
        for x, y, z in self.verts:
            x, z = x * math.cos(a) - z * math.sin(a), x * math.sin(a) + z * math.cos(a)
            y, z = y * math.cos(b) - z * math.sin(b), y * math.sin(b) + z * math.cos(b)
            k = 3.2 / (z + 5)
            pts.append((cx + x * r * k, cy + y * r * k, z))
        for item, (i, j) in zip(self.edge_items, self.edges):
            depth = (pts[i][2] + pts[j][2]) / 2
            self.coords(item, pts[i][0], pts[i][1], pts[j][0], pts[j][1])
            self.itemconfigure(item, fill=_mix(NEON[0], "#1b3050", (depth + 1.9) / 3.8))

    def _frame_shader(self):
        w, h, t = self.w, self.h, self.t
        tt = t * 0.08
        for r, row in enumerate(self.cells):   # the plasma: a sum of sines per cell, through a cycling palette
            for c, item in enumerate(row):
                v = (math.sin(c * 0.35 + tt) + math.sin(r * 0.45 + tt * 1.3) + math.sin((c + r) * 0.25 + tt * 0.7)
                     + math.sin(math.hypot(c - 16 + 6 * math.sin(tt * 0.5), r - 7 + 4 * math.cos(tt * 0.4)) * 0.6))
                self.itemconfigure(item, fill=self.palette[int((v + 4) * 8 + t) % 64])
        cx, cy, rad = w / 2, h * 0.42, min(w, h) * 0.17   # the ball of dots, lit from the top left
        a, b = t * 0.035, 0.5 + 0.3 * math.sin(t * 0.02)
        for item, (x, y, z) in zip(self.ball_items, self.ball):
            x, z = x * math.cos(a) - z * math.sin(a), x * math.sin(a) + z * math.cos(a)
            y, z = y * math.cos(b) - z * math.sin(b), y * math.sin(b) + z * math.cos(b)
            light = max(0.0, (-x * 0.5 - y * 0.6 - z * 0.62))
            s = 2.2 + 3.4 * (1 - (z + 1) / 2)
            px, py = cx + x * rad, cy + y * rad
            self.coords(item, px - s, py - s, px + s, py + s)
            self.itemconfigure(item, fill=_mix("#3a1868", "#ffffff", 0.3 + 0.7 * light) if z < 0.2 else "#1c0f38")

    def _frame_common(self):
        w, h, t = self.w, self.h, self.t
        self.itemconfigure(self.title_item, fill=NEON[(t // 45) % len(NEON)])
        offset = (t * 3) % (len(SCROLL) * self.char_w)   # sine scroller
        first = int(offset // self.char_w); sub = offset % self.char_w
        base = h * 0.66 if self.style != "stars" else h * 0.55
        for i, item in enumerate(self.scroll_items):
            ch = SCROLL[(first + i) % len(SCROLL)]
            x = i * self.char_w - sub
            y = base + math.sin((x + t * 4) * 0.018) * (12 if self.style != "stars" else 22)
            self.itemconfigure(item, text=ch, fill=NEON[(i // 6 + t // 20) % len(NEON)] if ch != " " else BG)
            self.coords(item, x, y)
        lit = int(round(self.fraction * self.seg_n))
        for i, seg in enumerate(self.segs):
            on = i < lit
            glow = on and (i == lit - 1) and (t // 8) % 2
            self.itemconfigure(seg, fill=("#ffffff" if glow else _mix(NEON[0], NEON[1], i / self.seg_n)) if on else "#141226")
        self.itemconfigure(self.pct_item, text=f"{self.step}   {self.fraction * 100:5.1f} %" if self.step else f"{self.fraction * 100:5.1f} %")
        self.itemconfigure(self.detail_item, text=self.detail)
