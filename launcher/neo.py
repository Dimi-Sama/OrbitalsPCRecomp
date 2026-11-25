# Orbitals PC Recomp, a work based on SwitchRecomp by MZ Labs. GNU AGPL v3.0 with the additional terms of NOTICE.txt (LICENSE.txt).
"""The launcher's title screen, drawn by hand on one Tk canvas (no stock widget look): a 90s anime title-screen style of our own, with
diagonal duotone panels, big display type, a starfield and sparkles, and a menu that the mouse, the keyboard (arrows, Enter) and a
controller drive. The menu holds places; what needs the player is a card on the left, above the state's chips, which lead to their
pages. Draws only; what the entries do comes from the caller (ui.py), which keeps the launcher's logic."""
import ctypes
import math
import os
import random
import tkinter as tk
from tkinter import font

from .look import px

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


class Spot:
    """A place of the title screen that can be chosen: an entry of the menu, or something of the left panel."""

    def __init__(self, kind, run, enabled=True, label="", hint=""):
        self.kind, self.run, self.enabled, self.label, self.hint = kind, run, enabled, label, hint
        self.box = (0, 0, 0, 0)

    def middle(self):
        return (self.box[0] + self.box[2]) / 2, (self.box[1] + self.box[3]) / 2


class Card:
    """What the title screen has to say: a title, a text and what can be done about it [(label, run)], the first the main one."""

    def __init__(self, title, text, buttons, alarm=False):
        self.title, self.text, self.buttons, self.alarm = title, text, buttons, alarm


class TitleScreen(tk.Canvas):
    """menu: [(label, hint, run, enabled)]; tags: [(title, value, colour, run)] shown as the 'PLAYER 1'-style chips; card: a Card or
    None; pads: (text, connected, run) for the controllers' line, or None. still(): True while the stars should not move (a game is
    running); they also stop while nobody can see them."""

    def __init__(self, parent, menu, tags, subtitle="", card=None, pads=None, footer="", still=lambda: False, animate=True, **options):
        super().__init__(parent, bg=NIGHT, highlightthickness=0, takefocus=1, **options)
        fam = set(font.families())
        self.disp = pick(fam, "Bahnschrift", "DejaVu Sans Condensed", "Liberation Sans Narrow", "Arial Narrow", "TkDefaultFont")
        body = pick(fam, "Segoe UI", "Noto Sans", "DejaVu Sans", "TkDefaultFont")
        self.f_kana = (pick(fam, "Yu Gothic UI", "Meiryo", "Noto Sans CJK JP", "MS Gothic", body), 20, "bold")
        self.f_hint = font.Font(family=body, size=10); self.f_small = font.Font(family=body, size=9)
        self.f_bold = font.Font(family=body, size=10, weight="bold"); self.f_tag = font.Font(family=self.disp, size=11, weight="bold")
        self.f_card = font.Font(family=self.disp, size=13, weight="bold")
        self.menu, self.tags, self.subtitle, self.card, self.pads, self.footer, self.still = menu, tags, subtitle, card, pads, footer, still
        self.entries = [Spot("menu", run, enabled, label, hint) for label, hint, run, enabled in menu]
        self.buttons = [Spot("button", run, label=label) for label, run in (card.buttons if card else ())]
        self.pads_spot = Spot("pads", pads[2]) if pads else None
        self.chips = [Spot("chip", tag[3]) for tag in tags]
        self.spots = self.entries + ([self.pads_spot] if self.pads_spot else []) + self.buttons + self.chips
        self.selected = next((spot for spot in self.entries if spot.enabled), self.entries[0])
        self.t = 0; self.running = False; self.cells = []
        self.moves = animate and motion_allowed()
        self.bind("<Configure>", lambda e: self._draw())
        self.bind("<Map>", lambda e: self._start()); self.bind("<Destroy>", lambda e: self._stop())
        for key, x, y in (("<Up>", 0, -1), ("<Down>", 0, 1), ("<Left>", -1, 0), ("<Right>", 1, 0)):
            self.bind(key, lambda e, x=x, y=y: self.go(x, y))
        self.bind("<Return>", lambda e: self.take(self.selected)); self.bind("<space>", lambda e: self.take(self.selected))
        self.bind("<Motion>", self._hover); self.bind("<Button-1>", self._click)

    # ---- input ----
    def go(self, x, y):
        """Choose the next place in a direction: up and down go round the menu; elsewhere the nearest one that way."""
        if y and self.selected.kind == "menu":
            places = [spot for spot in self.entries if spot.enabled]
            if places:
                at = places.index(self.selected) if self.selected in places else 0
                self._select(places[(at + y) % len(places)])
            return "break"
        if x > 0 and self.selected.kind == "menu":
            return "break"
        cx, cy = self.selected.middle()
        best = None
        for spot in self.spots:
            if spot is self.selected or not spot.enabled or (y and spot.kind == "menu"):
                continue
            dx, dy = spot.middle()[0] - cx, spot.middle()[1] - cy
            ahead, aside = (dx * x, abs(dy)) if x else (dy * y, abs(dx))
            if ahead > 2 and (best is None or ahead + 2 * aside < best[0]):
                best = (ahead + 2 * aside, spot)
        if best:
            self._select(best[1])
        return "break"

    def take(self, spot):
        if spot.enabled and spot.run:
            spot.run()
        return "break"

    def _select(self, spot):
        if spot is not self.selected:
            self.selected = spot
            self._draw_spots()

    def _spot_at(self, x, y):
        return next((s for s in self.spots if s.enabled and s.box[0] <= x <= s.box[2] and s.box[1] <= y <= s.box[3]), None)

    def _hover(self, e):
        spot = self._spot_at(e.x, e.y)
        if spot:
            self._select(spot)
        hand(self, spot is not None)

    def _click(self, e):
        self.focus_set()
        spot = self._spot_at(e.x, e.y)
        if spot:
            self.take(spot)

    # ---- drawing ----
    def _start(self):
        if self.grab_current() is None:   # (not from under a dialog)
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
        """the width left for something from x at height y, before the diagonal"""
        return self._split(y) - px(38) - x

    def _draw(self):
        self.delete("all")
        w, h = max(self.winfo_width(), 400), max(self.winfo_height(), 300); self.w, self.h = w, h
        # diagonal duotone panels (left blue, right pink), the split leaning like a title card
        split_top, split_bot = self._split(0), self._split(h)
        self.create_polygon(0, 0, split_top, 0, split_bot, h, 0, h, fill=BLUE_D, outline="")
        self.create_polygon(0, 0, split_top - px(26), 0, split_bot - px(26), h, 0, h, fill=BLUE, outline="")
        # glow rays behind the logo (drawn before the pink panel, which covers their other half)
        cx, cy = w * 0.25, h * 0.34
        for k in range(14):
            a = k / 14 * math.tau
            self.create_line(cx, cy, cx + math.cos(a) * w, cy + math.sin(a) * w, fill="#4f78ff", width=px(2))
        self.create_polygon(split_top + px(14), 0, w, 0, w, h, split_bot + px(14), h, fill=PINK_D, outline="")
        self.create_line(split_top, 0, split_bot, h, fill=INK, width=px(4))
        self.create_line(split_top + px(14), 0, split_bot + px(14), h, fill=GOLD, width=px(2))
        # the places, then what is drawn under and around them
        left, up = px(40), h * (0.10 if self.card else 0)   # a card takes the logo up a little
        tag_top = h * 0.42 - up
        self._place_menu()
        self._place_chips(left, h - px(92))
        line = tag_top + px(36)
        if self.pads_spot:
            width = min(self._room(left, line + px(40)), self.f_hint.measure(self.pads[0]) + px(52))
            self.pads_spot.box = (left - px(8), line, left - px(8) + width, line + px(28))
        self._place_card(left, line + (px(40) if self.pads_spot else px(8)), h - px(106))
        self._draw_sky(w, h, tag_top)
        for y in range(0, h, 4):   # faint scanlines, over the panels and under the texts
            self.create_line(0, y, w, y, fill="#05061a", stipple="gray12")
        # logo block
        logo_y = h * 0.32 - up
        logo = fitting(self.disp, 64, 32, ("ORBITALS",), self._room(left, logo_y + px(40)))
        self.create_text(px(42), h * 0.20 - up, text="オービタルズ", font=self.f_kana, fill=CYAN, anchor="w")
        self.create_text(px(40), logo_y + px(5), text="ORBITALS", font=logo, fill="#0b1240", anchor="w")
        self.create_text(px(36), logo_y, text="ORBITALS", font=logo, fill=INK, anchor="w")
        tag = "LIFTOFF · PC RECOMP"
        tag_w = self.f_tag.measure(tag) + px(20)
        self.create_rectangle(left, tag_top, left + tag_w, tag_top + px(26), fill=PINK, outline="")
        self.create_text(left + px(10), tag_top + px(13), text=tag, font=self.f_tag, fill=NIGHT, anchor="w")
        self.create_text(left + tag_w + px(12), tag_top + px(13), text="▶", font=self.f_tag, fill=INK, anchor="w")
        if self.subtitle and not self.card:
            y = line + px(40) if self.pads_spot else line
            self.create_text(px(42), y, text=self.subtitle, font=self.f_hint, fill=INK, anchor="nw", width=self._room(px(42), y + px(60)))
        credit, more = "SwitchRecomp by MZ Labs", "  ·  your own copy, recompiled on your machine"
        self.create_text(px(42), h - px(20), text=credit + more if self.f_small.measure(credit + more) <= self._room(px(42), h) else credit,
                         font=self.f_small, fill=INK, anchor="w")
        if self.footer and self.entries[-1].box[3] < h - px(36):
            self.create_text(w - px(24), h - px(20), text=shortened(self.footer, self.f_small, w - px(60) - split_bot), font=self.f_small,
                             fill="#ffd3e4", anchor="e")
        self._draw_spots()

    def _draw_sky(self, w, h, logo_bottom):
        """Stars and sparkles, where there is no text; the stars are kept per cell of the screen, for _tick."""
        rnd = random.Random(3)
        self.cells = [[] for _ in range(CELLS[0] * CELLS[1])]
        boxes = [spot.box for spot in self.spots] + ([self.card_box] if self.card else [])
        boxes.append((0, 0.06 * h, self._split(0), logo_bottom + px(30 if self.card else 120)))   # the logo and what is under it
        boxes.append((0, h - px(36), w, h))

        def over_text(x, y, margin):
            return any(left - margin < x < right + margin and top - margin < y < bottom + margin for left, top, right, bottom in boxes)

        for _ in range(120):
            x, y, s = rnd.uniform(0, w), rnd.uniform(0, h), px(rnd.choice((1, 1, 1, 2, 2, 3)))
            if over_text(x, y, px(4)):
                continue
            item = self.create_oval(x, y, x + s, y + s, fill="#ffffff", outline="")
            column, row = min(int(x / w * CELLS[0]), CELLS[0] - 1), min(int(y / h * CELLS[1]), CELLS[1] - 1)
            self.cells[row * CELLS[0] + column].append((item, rnd.uniform(0, 6.28)))
        for _ in range(7):   # four-point sparkles
            x, y, r = rnd.uniform(w * 0.05, w * 0.95), rnd.uniform(h * 0.05, h * 0.95), px(rnd.uniform(5, 11))
            if over_text(x, y, px(14)):
                continue
            self.create_polygon(x, y - r, x + r * 0.22, y - r * 0.22, x + r, y, x + r * 0.22, y + r * 0.22, x, y + r, x - r * 0.22, y + r * 0.22,
                                x - r, y, x - r * 0.22, y - r * 0.22, fill="#fff6d8", outline="")

    def _place_chips(self, x, y):
        """State chips, bottom left ("PLAYER 1"-style tags), kept left of the diagonal: smaller, then shortened, when they do not fit."""
        room = self._room(x, y + px(52))
        for size, pad, gap in ((16, 30, 14), (14, 24, 10), (12, 20, 8)):
            pad, gap = px(pad), px(gap)
            self.f_value = font.Font(family=self.disp, size=size, weight="bold")
            widths = [max(self.f_tag.measure(tag[0]), self.f_value.measure(tag[1])) + pad for tag in self.tags]
            if sum(widths) + gap * (len(widths) - 1) <= room:
                break
        else:   # the last chip (the profile, up to 32 characters) gives way
            widths[-1] = max(self.f_tag.measure(self.tags[-1][0]) + pad, room - sum(widths[:-1]) - gap * (len(widths) - 1))
        for spot, width in zip(self.chips, widths):
            spot.box = (x, y, x + width, y + px(56))
            x += width + gap

    def _place_card(self, x, top, bottom):
        """The card between the logo and the chips: its text gives way when the window is low."""
        if not self.card:
            return
        room = min(self._room(x, bottom), px(460)) - px(32)
        line = self.f_hint.metrics("linespace")
        self.card_title = fitting(self.disp, 13, 10, (self.card.title,), room)
        widths = [self.f_bold.measure(spot.label) + px(28) for spot in self.buttons]
        stacked = sum(widths) + px(8) * max(0, len(widths) - 1) > room
        button_h = px(36)
        rows = len(widths) if stacked else min(1, len(widths))
        fixed = px(14) + self.card_title.metrics("linespace") + px(4) + (px(12) + rows * button_h + px(6) * max(0, rows - 1) if rows else 0) + px(14)
        lines = max(1, int((bottom - top - fixed) / line))
        self.card_lines = self._wrapped(self.card.text, room, lines)
        height = fixed + line * len(self.card_lines)
        self.card_box = (x, top, x + room + px(32), top + height)
        bx, by = x + px(18), top + height - px(14) - rows * button_h - px(6) * max(0, rows - 1)
        for spot, width in zip(self.buttons, widths):
            spot.box = (bx, by, bx + width, by + button_h)
            if stacked:
                by += button_h + px(6)
            else:
                bx += width + px(8)

    def _wrapped(self, text, width, lines):
        out = []
        for paragraph in text.split("\n"):
            current = ""
            for word in paragraph.split():
                longer = f"{current} {word}".strip()
                if self.f_hint.measure(longer) <= width or not current:
                    current = longer
                else:
                    out.append(current); current = word
            out.append(current)
        out = [shortened(line, self.f_hint, width) for line in out if line]
        if len(out) > lines:
            out = out[:lines]
            out[-1] = shortened(out[-1] + " …", self.f_hint, width)
        return out

    def _place_menu(self):
        """The entries' places: the largest type that fits beside the diagonal, hints wrapped, the block kept inside the window."""
        w, h = self.w, self.h
        self.x0 = w * 0.62
        self.hint_width = w - px(60) - self.x0
        self.f_menu = fitting(self.disp, 26, 16, [m[0] for m in self.menu], self.hint_width)
        line, hint = self.f_menu.metrics("linespace"), self.f_hint.metrics("linespace")
        heights = [line + (hint * (1 if self.f_hint.measure(m[1]) <= self.hint_width else 2) if m[1] else 0) + px(4) for m in self.menu]
        gap = max(px(6), min(px(16), (h - px(48) - sum(heights)) / max(1, len(heights))))
        y = max(px(16), min(h * 0.24, (h - sum(heights) - gap * (len(heights) - 1)) / 2))
        for spot, height in zip(self.entries, heights):
            spot.box = (self.x0 - px(46), y - px(4), w - px(30), y + height + px(2))
            y += height + gap

    def _draw_spots(self):
        self.delete("spots")
        text = lambda *place, **look: self.create_text(*place, tags="spots", **look)
        line = self.f_menu.metrics("linespace")
        for spot in self.entries:
            left, top, right, bottom = spot.box
            on, slant = spot is self.selected and spot.enabled, px(16)
            if on:   # the selected entry: a slanted bar with a cursor, like a game menu
                self.create_polygon(left + slant, top, right, top, right - slant, bottom, left, bottom, fill=INK, outline="", tags="spots")
                text(self.x0 - px(22), top + px(4) + line / 2, text="▶", font=self.f_tag, fill=PINK_D, anchor="w")
            text(self.x0, top + px(3), text=spot.label, font=self.f_menu, fill=PINK_D if on else (INK if spot.enabled else DIM), anchor="nw")
            text(self.x0 + px(2), top + px(3) + line, text=spot.hint, font=self.f_hint, width=self.hint_width,
                 fill=BLUE_D if on else ("#ffd3e4" if spot.enabled else DIM), anchor="nw")
        if self.pads_spot:
            left, top, right, bottom = self.pads_spot.box
            y = (top + bottom) / 2
            self.create_oval(left + px(10), y - px(4), left + px(18), y + px(4), fill=CYAN if self.pads[1] else "", outline=INK, tags="spots")
            text(left + px(28), y, text=shortened(self.pads[0], self.f_hint, right - left - px(44)), font=self.f_hint, fill=INK, anchor="w")
        if self.card:
            left, top, right, bottom = self.card_box
            self.create_rectangle(left, top, right, bottom, fill=NIGHT, outline=PINK if self.card.alarm else CYAN, tags="spots")
            self.create_rectangle(left, top, left + px(5), bottom, fill=PINK if self.card.alarm else CYAN, outline="", tags="spots")
            y = top + px(14)
            text(left + px(18), y, text=shortened(self.card.title, self.card_title, right - left - px(32)), font=self.card_title, fill=INK, anchor="nw")
            y += self.card_title.metrics("linespace") + px(4)
            for words in self.card_lines:
                text(left + px(18), y, text=words, font=self.f_hint, fill="#c9d4ff", anchor="nw")
                y += self.f_hint.metrics("linespace")
            for number, spot in enumerate(self.buttons):
                main, on = number == 0, spot is self.selected
                self.create_rectangle(*spot.box, fill=INK if on else (CYAN if main else "#232b73"), outline="", tags="spots")
                text(*spot.middle(), text=spot.label, font=self.f_bold, fill=NIGHT if on or main else INK)
        for spot, (title, value, colour, _run) in zip(self.chips, self.tags):
            left, top, right, _bottom = spot.box
            self.create_rectangle(left, top, right, top + px(22), fill=colour, outline="", tags="spots")
            text(left + px(10), top + px(11), text=title, font=self.f_tag, fill=NIGHT, anchor="w")
            text(left + px(10), top + px(40), text=shortened(value, self.f_value, right - left - px(12)), font=self.f_value, fill=INK, anchor="w")
        if self.selected.kind in ("pads", "chip"):
            left, top, right, bottom = self.selected.box
            self.create_rectangle(left - px(3), top - px(3), right + px(3), bottom + px(3), outline=INK, width=px(2), tags="spots")

    def set_pads(self, text, connected, footer):
        """The controllers changed: their line, and what the footer says about the keys."""
        if self.pads_spot and (text, connected) != self.pads[:2]:
            self.pads, self.footer = (text, connected, self.pads[2]), footer
            self._draw()

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
        super().__init__(parent, bg=NIGHT, highlightthickness=0, height=px(height), takefocus=1)
        fam = set(font.families())
        disp = pick(fam, "Bahnschrift", "DejaVu Sans Condensed", "Liberation Sans Narrow", "Arial Narrow", "TkDefaultFont")
        self.f_title = font.Font(family=disp, size=24, weight="bold"); self.f_tab = font.Font(family=disp, size=13, weight="bold")
        self.f_back = font.Font(family=disp, size=12, weight="bold")
        self.title, self.tabs, self.current, self.tall = title, tabs, current, px(height)
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
        tw = self.f_title.measure(self.title) + px(40)
        x0 = px(140)
        split = max(w * 0.42, x0 + tw + px(50))   # right of the title, however wide
        self.create_polygon(0, 0, split, 0, split - px(30), h, 0, h, fill=BLUE_D, outline="")
        self.create_line(split, 0, split - px(30), h, fill=GOLD, width=px(2))
        self.create_line(split + px(10), 0, split - px(20), h, fill=INK, width=px(3))
        self.create_text(px(26), h / 2, text="◀  BACK", font=self.f_back, fill=CYAN, anchor="w")
        self.boxes = [(px(16), px(36) + back_w)]
        edge, slant = px(20), px(12)
        self.create_polygon(x0, edge, x0 + tw, edge, x0 + tw - slant, h - edge, x0 - slant, h - edge, fill=PINK, outline="")
        self.create_text(x0 + px(10), h / 2, text=self.title, font=self.f_title, fill=NIGHT, anchor="w")
        x = split + px(40)
        for page, lab in self.tabs:
            on = page == self.current
            lw = self.f_tab.measure(lab)
            self.create_text(x, h / 2, text=lab, font=self.f_tab, fill=INK if on else MUTED, anchor="w")
            if on:
                self.create_rectangle(x, h / 2 + px(14), x + lw, h / 2 + px(17), fill=CYAN, outline="")
            self.boxes.append((x - px(12), x + lw + px(12)))
            x += lw + px(34)
        if self.focused:
            left, right = self.boxes[self.cursor]
            self.create_rectangle(left, h / 2 - px(22), right, h / 2 + px(22), outline=CYAN, width=px(2))
        self.create_line(0, h - 1, w, h - 1, fill=LINE_C, width=1)
