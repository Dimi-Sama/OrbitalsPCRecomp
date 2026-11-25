# Orbitals PC Recomp, a work based on SwitchRecomp by MZ Labs. GNU AGPL v3.0 with the additional terms of NOTICE.txt (LICENSE.txt).
"""The launcher's title screen, drawn by hand on one Tk canvas (no stock widget look): a 90s anime title-screen style of our own, with
diagonal duotone panels, big display type, a starfield and sparkles, and a menu that the mouse, the keyboard (arrows, Enter) and later a
controller drive. Draws only; what the entries do comes from the caller (ui.py), which keeps the launcher's logic."""
import math
import random
import tkinter as tk
from tkinter import font

INK = "#f4f1ff"
NIGHT = "#090a1c"
BLUE = "#2e5cff"
BLUE_D = "#1a2f8f"
PINK = "#ff4f8b"
PINK_D = "#8f1f4d"
CYAN = "#46e6ff"
GOLD = "#ffc94a"
MUTED = "#8f8fb8"
LINE_C = "#2d3b94"
FRAME_MS = 40


def pick(families, *wanted):
    return next((f for f in wanted if f in families), wanted[-1])


class TitleScreen(tk.Canvas):
    """menu: [(label, hint, callback, enabled)]; tags: [(title, value, colour)] shown as the 'PLAYER 1'-style chips."""

    def __init__(self, parent, menu, tags, subtitle="", **options):
        super().__init__(parent, bg=NIGHT, highlightthickness=0, **options)
        fam = set(font.families())
        disp = pick(fam, "Bahnschrift", "DejaVu Sans Condensed", "Liberation Sans Narrow", "Arial Narrow", "TkDefaultFont")
        body = pick(fam, "Segoe UI", "Noto Sans", "DejaVu Sans", "TkDefaultFont")
        self.f_logo = (disp, 64, "bold"); self.f_kana = (pick(fam, "Yu Gothic UI", "Meiryo", "Noto Sans CJK JP", "MS Gothic", body), 20, "bold")
        self.f_menu = (disp, 26, "bold"); self.f_hint = (body, 10); self.f_tag = (disp, 11, "bold"); self.f_val = (disp, 16, "bold")
        self.f_small = (body, 9)
        self.menu, self.tags, self.subtitle = menu, tags, subtitle
        self.sel = next((i for i, m in enumerate(menu) if m[3]), 0)
        self.t = 0; self.running = False; self.stars = []
        self.bind("<Configure>", lambda e: self._draw())
        self.bind("<Map>", lambda e: self._start()); self.bind("<Destroy>", lambda e: setattr(self, "running", False))
        self.bind("<Up>", lambda e: self._move(-1)); self.bind("<Down>", lambda e: self._move(1))
        self.bind("<Return>", lambda e: self._activate(self.sel)); self.bind("<space>", lambda e: self._activate(self.sel))
        self.bind("<Motion>", self._hover); self.bind("<Button-1>", self._click)

    # ---- input ----
    def _move(self, d):
        n = len(self.menu)
        for _ in range(n):
            self.sel = (self.sel + d) % n
            if self.menu[self.sel][3]: break
        self._draw_menu()

    def _activate(self, i):
        if 0 <= i < len(self.menu) and self.menu[i][3] and self.menu[i][2]:
            self.menu[i][2]()

    def _item_at(self, x, y):
        for i, box in enumerate(getattr(self, "boxes", [])):
            if box[0] <= x <= box[2] and box[1] <= y <= box[3]: return i
        return None

    def _hover(self, e):
        i = self._item_at(e.x, e.y)
        if i is not None and i != self.sel and self.menu[i][3]:
            self.sel = i; self._draw_menu()
        self.configure(cursor="hand2" if i is not None and self.menu[i][3] else "")

    def _click(self, e):
        self.focus_set()
        i = self._item_at(e.x, e.y)
        if i is not None: self._activate(i)

    # ---- drawing ----
    def _start(self):
        self.focus_set()
        if not self.running:
            self.running = True; self.after(FRAME_MS, self._tick)

    def _draw(self):
        self.delete("all")
        w, h = max(self.winfo_width(), 400), max(self.winfo_height(), 300); self.w, self.h = w, h
        # diagonal duotone panels (left blue, right pink), the split leaning like a title card
        split_top, split_bot = w * 0.56, w * 0.44
        self.create_polygon(0, 0, split_top, 0, split_bot, h, 0, h, fill=BLUE_D, outline="")
        self.create_polygon(0, 0, split_top - 26, 0, split_bot - 26, h, 0, h, fill=BLUE, outline="")
        # glow rays behind the logo (drawn before the pink panel, which covers their other half)
        cx, cy = w * 0.25, h * 0.34
        for k in range(14):
            a = k / 14 * math.tau
            self.create_line(cx, cy, cx + math.cos(a) * w, cy + math.sin(a) * w, fill="#4f78ff", width=2)
        self.create_polygon(split_top + 14, 0, w, 0, w, h, split_bot + 14, h, fill=PINK_D, outline="")
        self.create_line(split_top, 0, split_bot, h, fill=INK, width=4)
        self.create_line(split_top + 14, 0, split_bot + 14, h, fill=GOLD, width=2)
        rnd = random.Random(3)   # stars and sparkles over the panels
        self.stars = []
        for _ in range(120):
            x, y, s = rnd.uniform(0, w), rnd.uniform(0, h), rnd.choice((1, 1, 1, 2, 2, 3))
            self.stars.append((self.create_oval(x, y, x + s, y + s, fill="#ffffff", outline=""), rnd.uniform(0, 6.28)))
        for _ in range(7):   # four-point sparkles
            x, y, r = rnd.uniform(w * 0.05, w * 0.95), rnd.uniform(h * 0.05, h * 0.95), rnd.uniform(5, 11)
            self.create_polygon(x, y - r, x + r * 0.22, y - r * 0.22, x + r, y, x + r * 0.22, y + r * 0.22, x, y + r, x - r * 0.22, y + r * 0.22,
                                x - r, y, x - r * 0.22, y - r * 0.22, fill="#fff6d8", outline="")
        # logo block
        self.create_text(42, h * 0.20, text="オービタルズ", font=self.f_kana, fill=CYAN, anchor="w")
        self.create_text(36 + 4, h * 0.32 + 5, text="ORBITALS", font=self.f_logo, fill="#0b1240", anchor="w")
        self.create_text(36, h * 0.32, text="ORBITALS", font=self.f_logo, fill=INK, anchor="w")
        self.create_rectangle(40, h * 0.42, 40 + 170, h * 0.42 + 26, fill=PINK, outline="")
        self.create_text(50, h * 0.42 + 13, text="LIFTOFF · PC RECOMP", font=self.f_tag, fill=INK, anchor="w")
        self.create_text(222, h * 0.42 + 13, text="▶", font=self.f_tag, fill=INK, anchor="w")
        if self.subtitle:
            self.create_text(42, h * 0.42 + 48, text=self.subtitle, font=self.f_hint, fill="#c9d4ff", anchor="w")
        # state chips, bottom left ("PLAYER 1"-style tags)
        x = 40; y = h - 92
        for title, value, colour in self.tags:
            tw = max(font.Font(font=self.f_tag).measure(title), font.Font(font=self.f_val).measure(value)) + 30
            self.create_rectangle(x, y, x + tw, y + 22, fill=colour, outline="")
            self.create_text(x + 10, y + 11, text=title, font=self.f_tag, fill=NIGHT, anchor="w")
            self.create_text(x + 10, y + 40, text=value, font=self.f_val, fill=INK, anchor="w")
            x += tw + 14
        self.create_text(42, h - 22, text="SwitchRecomp by MZ Labs  ·  your own copy, recompiled on your machine", font=self.f_small, fill="#aab4e8", anchor="w")
        self._draw_menu()
        for y in range(0, h, 4):   # faint scanlines
            self.create_line(0, y, w, y, fill="#05061a", stipple="gray12")

    def _draw_menu(self):
        self.delete("menu")
        w, h = self.w, self.h
        x0 = w * 0.62; y = h * 0.24; self.boxes = []
        for i, (lab, hint, _cb, enabled) in enumerate(self.menu):
            on = i == self.sel and enabled
            if on:   # the selected entry: a slanted bar with a cursor, like a game menu
                self.create_polygon(x0 - 30, y - 4, w - 30, y - 4, w - 46, y + 50, x0 - 46, y + 50, fill=INK, outline="", tags="menu")
                self.create_text(x0 - 22, y + 23, text="▶", font=self.f_tag, fill=PINK, anchor="w", tags="menu")
            colour = PINK_D if on else (INK if enabled else MUTED)
            self.create_text(x0, y + 16, text=lab, font=self.f_menu, fill=colour, anchor="w", tags="menu")
            self.create_text(x0 + 2, y + 39, text=hint, font=self.f_hint, fill=(BLUE_D if on else ("#ffd3e4" if enabled else MUTED)), anchor="w", tags="menu")
            self.boxes.append((x0 - 46, y - 4, w - 30, y + 50))
            y += 70

    def _tick(self):
        if not self.running: return
        try:
            self.t += 1
            for item, ph in self.stars:   # twinkle
                v = 0.5 + 0.5 * math.sin(self.t * 0.12 + ph)
                c = int(110 + 145 * v); self.itemconfigure(item, fill=f"#{c:02x}{c:02x}ff")
        except tk.TclError:
            self.running = False; return
        self.after(FRAME_MS, self._tick)


def header_strip(parent, title, tabs, current, on_tab, on_back, height=86):
    """A sub-screen's header in the title screen's style: ◀ BACK, a slanted pink tag with the screen's title, its tabs (page, label);
    the current tab underlined. Escape (bound by the launcher) also goes back."""
    c = tk.Canvas(parent, bg=NIGHT, highlightthickness=0, height=height)
    fam = set(font.families())
    disp = pick(fam, "Bahnschrift", "DejaVu Sans Condensed", "Liberation Sans Narrow", "Arial Narrow", "TkDefaultFont")
    f_title, f_tab, f_back = (disp, 24, "bold"), (disp, 13, "bold"), (disp, 12, "bold")

    def draw(_e=None):
        c.delete("all")
        w = max(c.winfo_width(), 400)
        c.create_polygon(0, 0, w * 0.42, 0, w * 0.42 - 30, height, 0, height, fill=BLUE_D, outline="")
        c.create_line(w * 0.42, 0, w * 0.42 - 30, height, fill=GOLD, width=2)
        c.create_line(w * 0.42 + 10, 0, w * 0.42 - 20, height, fill=INK, width=3)
        back = c.create_text(26, height / 2, text="◀  BACK", font=f_back, fill=CYAN, anchor="w")
        c.tag_bind(back, "<Button-1>", lambda _e: on_back())
        c.tag_bind(back, "<Enter>", lambda _e: c.configure(cursor="hand2")); c.tag_bind(back, "<Leave>", lambda _e: c.configure(cursor=""))
        tw = font.Font(font=f_title).measure(title) + 40
        x0 = 140
        c.create_polygon(x0, 20, x0 + tw, 20, x0 + tw - 12, height - 20, x0 - 12, height - 20, fill=PINK, outline="")
        c.create_text(x0 + 10, height / 2, text=title, font=f_title, fill=INK, anchor="w")
        x = w * 0.42 + 40
        for page, lab in tabs:
            on = page == current
            t = c.create_text(x, height / 2, text=lab, font=f_tab, fill=INK if on else MUTED, anchor="w")
            lw = font.Font(font=f_tab).measure(lab)
            if on:
                c.create_rectangle(x, height / 2 + 14, x + lw, height / 2 + 17, fill=CYAN, outline="")
            c.tag_bind(t, "<Button-1>", lambda _e, p=page: on_tab(p))
            c.tag_bind(t, "<Enter>", lambda _e: c.configure(cursor="hand2")); c.tag_bind(t, "<Leave>", lambda _e: c.configure(cursor=""))
            x += lw + 34
        c.create_line(0, height - 1, w, height - 1, fill=LINE_C, width=1)

    c.bind("<Configure>", draw)
    return c
