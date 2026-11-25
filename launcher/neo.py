# Orbitals PC Recomp, a work based on SwitchRecomp by MZ Labs. GNU AGPL v3.0 with the additional terms of NOTICE.txt (LICENSE.txt).
"""The launcher's title screen, drawn by hand on one Tk canvas (no stock widget look): a 90s anime title-screen style of our own, with
diagonal duotone panels, big display type, a starfield and sparkles, and a menu that the mouse, the keyboard (arrows, Enter) and later a
controller drive. Draws only; what the entries do comes from the caller (ui.py), which keeps the launcher's logic."""
import ctypes
import math
import os
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
DIM = "#d6bccd"     # an entry that cannot be chosen now, on the pink panel
LINE_C = "#2d3b94"
FRAME_MS = 80       # one cell of stars per frame: Tk repaints that cell, not the whole window
CELLS = (8, 6)
STILL_MS = 500      # how often a still screen looks whether it may move again


def pick(families, *wanted):
    return next((f for f in wanted if f in families), wanted[-1])


def motion_allowed():
    """Whether the system's animations are on (Windows: Accessibility > Visual effects); on where it cannot be told."""
    if os.name == "nt":
        try:
            on = ctypes.c_int(1)
            if ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(on), 0):   # SPI_GETCLIENTAREAANIMATION
                return bool(on.value)
        except (OSError, AttributeError):
            pass
    return True


def fitting(family, size, least, texts, width):
    """The largest bold font of a family, from size down to least, that shows every text in width pixels."""
    for points in range(size, least, -1):
        f = font.Font(family=family, size=points, weight="bold")
        if all(f.measure(text) <= width for text in texts):
            return f
    return font.Font(family=family, size=least, weight="bold")


def shortened(text, f, width):
    """text, or its beginning with an ellipsis when it is wider than width pixels."""
    if f.measure(text) <= width:
        return text
    while text and f.measure(text + "…") > width:
        text = text[:-1]
    return text.rstrip() + "…"


def hand(canvas, on):
    """The pointer over something to click. Only when it changes: a canvas repaints itself whole for any configure, at each mouse move."""
    cursor = "hand2" if on else ""
    if str(canvas.cget("cursor")) != cursor:
        canvas.configure(cursor=cursor)


class TitleScreen(tk.Canvas):
    """menu: [(label, hint, callback, enabled)]; tags: [(title, value, colour)] shown as the 'PLAYER 1'-style chips.
    still(): True while the stars should not move (a game is running); they also stop while nobody can see them."""

    def __init__(self, parent, menu, tags, subtitle="", still=lambda: False, animate=True, **options):
        super().__init__(parent, bg=NIGHT, highlightthickness=0, **options)
        fam = set(font.families())
        self.disp = pick(fam, "Bahnschrift", "DejaVu Sans Condensed", "Liberation Sans Narrow", "Arial Narrow", "TkDefaultFont")
        body = pick(fam, "Segoe UI", "Noto Sans", "DejaVu Sans", "TkDefaultFont")
        self.f_kana = (pick(fam, "Yu Gothic UI", "Meiryo", "Noto Sans CJK JP", "MS Gothic", body), 20, "bold")
        self.f_hint = font.Font(family=body, size=10); self.f_small = font.Font(family=body, size=9)
        self.f_tag = font.Font(family=self.disp, size=11, weight="bold")
        self.menu, self.tags, self.subtitle, self.still = menu, tags, subtitle, still
        self.sel = next((i for i, m in enumerate(menu) if m[3]), 0)
        self.t = 0; self.running = False; self.cells = []; self.boxes = []
        self.moves = animate and motion_allowed()
        self.bind("<Configure>", lambda e: self._draw())
        self.bind("<Map>", lambda e: self._start()); self.bind("<Destroy>", lambda e: self._stop())
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
        for i, box in enumerate(self.boxes):
            if box[0] <= x <= box[2] and box[1] <= y <= box[3]: return i
        return None

    def _hover(self, e):
        i = self._item_at(e.x, e.y)
        if i is not None and i != self.sel and self.menu[i][3]:
            self.sel = i; self._draw_menu()
        hand(self, i is not None and self.menu[i][3])

    def _click(self, e):
        self.focus_set()
        i = self._item_at(e.x, e.y)
        if i is not None: self._activate(i)

    # ---- drawing ----
    def _start(self):
        self.focus_set()
        if not self.running:
            self.running = True; self.timer = self.after(FRAME_MS, self._tick)

    def _stop(self):
        if self.running:
            self.running = False; self.after_cancel(self.timer)

    def _split(self, y):
        """where the diagonal between the two panels is at height y"""
        return self.w * (0.56 - 0.12 * y / self.h)

    def _room(self, x, y):
        """the width left for a text from x at height y, before the diagonal"""
        return self._split(y) - 26 - 12 - x

    def _draw(self):
        self.delete("all")
        w, h = max(self.winfo_width(), 400), max(self.winfo_height(), 300); self.w, self.h = w, h
        # diagonal duotone panels (left blue, right pink), the split leaning like a title card
        split_top, split_bot = self._split(0), self._split(h)
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
        self._place_menu()
        self._draw_sky(w, h)
        for y in range(0, h, 4):   # faint scanlines, over the panels and under the texts
            self.create_line(0, y, w, y, fill="#05061a", stipple="gray12")
        # logo block
        logo = fitting(self.disp, 64, 32, ("ORBITALS",), self._room(40, h * 0.38))
        self.create_text(42, h * 0.20, text="オービタルズ", font=self.f_kana, fill=CYAN, anchor="w")
        self.create_text(36 + 4, h * 0.32 + 5, text="ORBITALS", font=logo, fill="#0b1240", anchor="w")
        self.create_text(36, h * 0.32, text="ORBITALS", font=logo, fill=INK, anchor="w")
        self.create_rectangle(40, h * 0.42, 40 + 170, h * 0.42 + 26, fill=PINK, outline="")
        self.create_text(50, h * 0.42 + 13, text="LIFTOFF · PC RECOMP", font=self.f_tag, fill=NIGHT, anchor="w")
        self.create_text(222, h * 0.42 + 13, text="▶", font=self.f_tag, fill=INK, anchor="w")
        if self.subtitle:
            self.create_text(42, h * 0.42 + 40, text=self.subtitle, font=self.f_hint, fill=INK, anchor="nw", width=self._room(42, h * 0.62))
        self._draw_tags(h)
        credit, more = "SwitchRecomp by MZ Labs", "  ·  your own copy, recompiled on your machine"
        self.create_text(42, h - 22, text=credit + more if self.f_small.measure(credit + more) <= self._room(42, h) else credit,
                         font=self.f_small, fill=INK, anchor="w")
        self._draw_menu()

    def _draw_sky(self, w, h):
        """Stars and sparkles, where there is no text; the stars are kept per cell of the screen, for _tick."""
        rnd = random.Random(3)
        self.cells = [[] for _ in range(CELLS[0] * CELLS[1])]
        top, bottom = (self.boxes[0][1], self.boxes[-1][3]) if self.boxes else (0, 0)

        def over_text(x, y, margin):   # the menu; the logo and the chips
            if x > self._split(y):
                return x > self.x0 - 10 - margin and top - margin < y < bottom + margin
            return 0.16 * h - margin < y < 0.54 * h or y > h - 100 - margin

        for _ in range(120):
            x, y, s = rnd.uniform(0, w), rnd.uniform(0, h), rnd.choice((1, 1, 1, 2, 2, 3))
            if over_text(x, y, 0):
                continue
            item = self.create_oval(x, y, x + s, y + s, fill="#ffffff", outline="")
            column, row = min(int(x / w * CELLS[0]), CELLS[0] - 1), min(int(y / h * CELLS[1]), CELLS[1] - 1)
            self.cells[row * CELLS[0] + column].append((item, rnd.uniform(0, 6.28)))
        for _ in range(7):   # four-point sparkles
            x, y, r = rnd.uniform(w * 0.05, w * 0.95), rnd.uniform(h * 0.05, h * 0.95), rnd.uniform(5, 11)
            if over_text(x, y, 12):
                continue
            self.create_polygon(x, y - r, x + r * 0.22, y - r * 0.22, x + r, y, x + r * 0.22, y + r * 0.22, x, y + r, x - r * 0.22, y + r * 0.22,
                                x - r, y, x - r * 0.22, y - r * 0.22, fill="#fff6d8", outline="")

    def _draw_tags(self, h):
        """State chips, bottom left ("PLAYER 1"-style tags), kept left of the diagonal: smaller, then shortened, when they do not fit."""
        x, y = 40, h - 92
        room = self._room(x, h - 40)
        for size, pad, gap in ((16, 30, 14), (14, 24, 10), (12, 20, 8)):
            value_font = font.Font(family=self.disp, size=size, weight="bold")
            widths = [max(self.f_tag.measure(title), value_font.measure(value)) + pad for title, value, _ in self.tags]
            if sum(widths) + gap * (len(widths) - 1) <= room:
                break
        else:   # the last chip (the profile, up to 32 characters) gives way
            widths[-1] = max(self.f_tag.measure(self.tags[-1][0]) + pad, room - sum(widths[:-1]) - gap * (len(widths) - 1))
        for (title, value, colour), tw in zip(self.tags, widths):
            self.create_rectangle(x, y, x + tw, y + 22, fill=colour, outline="")
            self.create_text(x + 10, y + 11, text=title, font=self.f_tag, fill=NIGHT, anchor="w")
            self.create_text(x + 10, y + 40, text=shortened(value, value_font, tw - 12), font=value_font, fill=INK, anchor="w")
            x += tw + gap

    def _place_menu(self):
        """The entries' places: the largest type that fits beside the diagonal, hints wrapped, the block kept inside the window."""
        w, h = self.w, self.h
        self.x0 = w * 0.62
        self.hint_width = w - 46 - 14 - self.x0
        self.f_menu = fitting(self.disp, 26, 16, [m[0] for m in self.menu], self.hint_width)
        line, hint = self.f_menu.metrics("linespace"), self.f_hint.metrics("linespace")
        heights = [line + hint * (1 if self.f_hint.measure(m[1]) <= self.hint_width else 2) + 4 for m in self.menu]
        gap = max(6, min(16, (h - 48 - sum(heights)) / max(1, len(heights))))
        y = max(16, min(h * 0.24, (h - sum(heights) - gap * (len(heights) - 1)) / 2))
        self.boxes = []
        for height in heights:
            self.boxes.append((self.x0 - 46, y - 4, w - 30, y + height + 2))
            y += height + gap

    def _draw_menu(self):
        self.delete("menu")
        line = self.f_menu.metrics("linespace")
        for i, ((lab, hint, _cb, enabled), (left, top, right, bottom)) in enumerate(zip(self.menu, self.boxes)):
            on = i == self.sel and enabled
            if on:   # the selected entry: a slanted bar with a cursor, like a game menu
                self.create_polygon(left + 16, top, right, top, right - 16, bottom, left, bottom, fill=INK, outline="", tags="menu")
                self.create_text(self.x0 - 22, top + 4 + line / 2, text="▶", font=self.f_tag, fill=PINK_D, anchor="w", tags="menu")
            self.create_text(self.x0, top + 3, text=lab, font=self.f_menu, fill=PINK_D if on else (INK if enabled else DIM), anchor="nw", tags="menu")
            self.create_text(self.x0 + 2, top + 3 + line, text=hint, font=self.f_hint, width=self.hint_width,
                             fill=BLUE_D if on else ("#ffd3e4" if enabled else DIM), anchor="nw", tags="menu")

    def _moving(self):
        """Nothing moves on a hidden or minimized window, behind another one, while a game runs, or with the system's animations off."""
        return self.moves and self.winfo_viewable() and self.focus_displayof() is not None and not self.still()

    def _tick(self):
        if not self.running: return
        try:
            moving = self._moving()
            if moving:
                for item, ph in self.cells[self.t % len(self.cells)] if self.cells else ():   # twinkle
                    c = int(110 + 145 * (0.5 + 0.5 * math.sin(self.t * 0.12 + ph))); self.itemconfigure(item, fill=f"#{c:02x}{c:02x}ff")
                self.t += 1
        except KeyError:   # the focus is in a native dialog, which Tkinter has no widget for
            moving = False
        except tk.TclError:
            self.running = False; return
        self.timer = self.after(FRAME_MS if moving else STILL_MS, self._tick)


class HeaderStrip(tk.Canvas):
    """A sub-screen's header in the title screen's style: ◀ BACK, a slanted pink tag with the screen's title, its tabs (page, label);
    the current tab underlined. Left and right go through BACK and the tabs, Enter takes one; down goes to the page (on_down)."""

    def __init__(self, parent, title, tabs, current, on_tab, on_back, on_down=lambda: None, height=86):
        super().__init__(parent, bg=NIGHT, highlightthickness=0, height=height, takefocus=1)
        fam = set(font.families())
        disp = pick(fam, "Bahnschrift", "DejaVu Sans Condensed", "Liberation Sans Narrow", "Arial Narrow", "TkDefaultFont")
        self.f_title = font.Font(family=disp, size=24, weight="bold"); self.f_tab = font.Font(family=disp, size=13, weight="bold")
        self.f_back = font.Font(family=disp, size=12, weight="bold")
        self.title, self.tabs, self.current, self.tall = title, tabs, current, height
        self.places = [on_back] + [lambda p=page: on_tab(p) for page, _ in tabs]
        self.cursor = next((i + 1 for i, (page, _) in enumerate(tabs) if page == current), 0)
        self.focused = False; self.boxes = []
        self.bind("<Configure>", lambda e: self.draw())
        self.bind("<FocusIn>", lambda e: self._focus(True)); self.bind("<FocusOut>", lambda e: self._focus(False))
        self.bind("<Left>", lambda e: self._move(-1)); self.bind("<Right>", lambda e: self._move(1))
        self.bind("<Down>", lambda e: on_down())
        self.bind("<Return>", lambda e: self.places[self.cursor]()); self.bind("<space>", lambda e: self.places[self.cursor]())
        self.bind("<Motion>", lambda e: hand(self, self._at(e) is not None))
        self.bind("<Button-1>", self._click)

    def _at(self, event):
        return next((i for i, (left, right) in enumerate(self.boxes) if left <= event.x <= right), None)

    def _click(self, event):
        at = self._at(event)
        if at is not None:
            self.places[at]()

    def _focus(self, on):
        self.focused = on
        self.draw()

    def _move(self, direction):
        self.cursor = max(0, min(len(self.places) - 1, self.cursor + direction))
        self.draw()

    def draw(self):
        self.delete("all")
        w, h = max(self.winfo_width(), 400), self.tall
        back_w = self.f_back.measure("◀  BACK")
        tw = self.f_title.measure(self.title) + 40
        x0 = 140
        split = max(w * 0.42, x0 + tw + 50)   # right of the title, however wide
        self.create_polygon(0, 0, split, 0, split - 30, h, 0, h, fill=BLUE_D, outline="")
        self.create_line(split, 0, split - 30, h, fill=GOLD, width=2)
        self.create_line(split + 10, 0, split - 20, h, fill=INK, width=3)
        self.create_text(26, h / 2, text="◀  BACK", font=self.f_back, fill=CYAN, anchor="w")
        self.boxes = [(16, 26 + back_w + 10)]
        self.create_polygon(x0, 20, x0 + tw, 20, x0 + tw - 12, h - 20, x0 - 12, h - 20, fill=PINK, outline="")
        self.create_text(x0 + 10, h / 2, text=self.title, font=self.f_title, fill=NIGHT, anchor="w")
        x = split + 40
        for page, lab in self.tabs:
            on = page == self.current
            lw = self.f_tab.measure(lab)
            self.create_text(x, h / 2, text=lab, font=self.f_tab, fill=INK if on else MUTED, anchor="w")
            if on:
                self.create_rectangle(x, h / 2 + 14, x + lw, h / 2 + 17, fill=CYAN, outline="")
            self.boxes.append((x - 12, x + lw + 12))
            x += lw + 34
        if self.focused:
            left, right = self.boxes[self.cursor]
            self.create_rectangle(left, h / 2 - 22, right, h / 2 + 22, outline=CYAN, width=2)
        self.create_line(0, h - 1, w, h - 1, fill=LINE_C, width=1)
