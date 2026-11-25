# SwitchRecomp - Copyright 2026 MZ Labs
"""The launcher's look: its colours, its ttk theme and the few plain widgets every page uses."""

import tkinter as tk
from tkinter import font, ttk

from .core import WINDOWS

# the title screen's palette (neo.py): night, blue, pink, gold
BG = "#0b0c22"
RAIL = "#11143a"
PANEL = "#161b4a"
ENTRY = "#0d1033"
LINE = "#2d3b94"
INK = "#f4f1ff"
MUTED = "#a3a8d6"
CYAN = "#46e6ff"
RED = "#ff4f8b"
PEACH = "#ffc94a"
DISABLED = "#7a80b8"   # a label of a control that cannot be used now
SELECTED = "#263080"   # the selected row
SCALE = 1.0            # pixels of this screen per pixel of the design (96 DPI)


def px(n):
    return round(n * SCALE)


def theme(root):
    installed = set(font.families(root))
    body = next((name for name in ("Segoe UI", "Noto Sans", "DejaVu Sans") if name in installed),
                font.nametofont("TkDefaultFont").actual("family"))
    heading = next((name for name in ("Bahnschrift SemiCondensed", "Bahnschrift", "DejaVu Sans")
                    if name in installed), body)
    for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont"):
        font.nametofont(name).configure(family=body, size=10)
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(".", background=BG, foreground=INK, bordercolor=LINE, font=(body, 10))
    style.configure("TButton", background=PANEL, foreground=INK, borderwidth=1,
                    lightcolor=PANEL, darkcolor=PANEL, focuscolor=CYAN, padding=(13, 8))
    style.map("TButton", background=[("disabled", RAIL), ("pressed", LINE), ("focus", SELECTED), ("active", "#222a66")],
              foreground=[("disabled", DISABLED)], bordercolor=[("focus", CYAN), ("active", "#5a6bd0")])
    style.configure("Play.TButton", background=RED, foreground=BG, padding=(23, 12),
                    lightcolor=RED, darkcolor=RED, bordercolor=RED, font=(heading, 13, "bold"))
    style.map("Play.TButton", background=[("disabled", PANEL), ("pressed", "#e03a74"), ("focus", "#ff8fb5"), ("active", "#ff77a5")],
              foreground=[("disabled", DISABLED)], bordercolor=[("focus", INK)])
    style.configure("TEntry", fieldbackground=ENTRY, insertcolor=INK, padding=(8, 5))
    style.configure("TCombobox", fieldbackground=ENTRY, arrowcolor=CYAN, padding=(7, 5))
    style.configure("TSpinbox", fieldbackground=ENTRY, arrowcolor=CYAN, insertcolor=INK, padding=(7, 5))
    style.map("TCombobox", fieldbackground=[("readonly", ENTRY)], selectbackground=[("readonly", ENTRY)],
              selectforeground=[("readonly", INK)], foreground=[("readonly", INK)])
    for name, ground in (("TCheckbutton", BG), ("Panel.TCheckbutton", PANEL)):   # on the page, on a card
        style.configure(name, background=ground, foreground=INK, indicatorbackground=ENTRY)
        style.map(name, indicatorbackground=[("selected", CYAN)],
                  background=[("active", ground)], foreground=[("disabled", DISABLED)])
    style.configure("TProgressbar", background=CYAN, troughcolor=ENTRY)
    style.layout("Vertical.TScrollbar", [("Vertical.Scrollbar.trough", {"sticky": "ns", "children": [
        ("Vertical.Scrollbar.thumb", {"expand": True, "sticky": "nswe"})]})])   # no arrows
    style.configure("Vertical.TScrollbar", background=LINE, troughcolor=RAIL, bordercolor=BG, lightcolor=LINE, darkcolor=LINE,
                    gripcount=0, width=px(10))
    style.map("Vertical.TScrollbar", background=[("disabled", RAIL), ("pressed", CYAN), ("active", "#5a6bd0")])
    root.option_add("*TCombobox*Listbox.background", ENTRY)
    root.option_add("*TCombobox*Listbox.foreground", INK)
    root.option_add("*TCombobox*Listbox.selectBackground", LINE)
    return body, heading


def surface(parent, background=PANEL):
    return tk.Frame(parent, bg=background, highlightthickness=1, highlightbackground=LINE)


def label(parent, text="", *, color=INK, size=10, bold=False, bg=BG, font_family=None, **options):
    family = font_family or font.nametofont("TkDefaultFont").actual("family")
    # left-aligned unless the caller says otherwise (passing anchor or justify here twice raised a TypeError: the home page did not open)
    return tk.Label(parent, text=text, fg=color, bg=bg, font=(family, size, "bold" if bold else "normal"),
                    **{"anchor": "w", "justify": "left", **options})


def text_box(parent, height=4):
    return tk.Text(parent, height=height, bg=ENTRY, fg=INK, insertbackground=INK,
                   selectbackground=LINE, highlightthickness=1, highlightbackground=LINE,
                   highlightcolor=CYAN, relief="flat", padx=9, pady=7, wrap="word",
                   font="TkTextFont", undo=True)


class ScrollPage(tk.Frame):
    """A page that scrolls when the window is shorter than it: `body` takes the widgets. The bar shows only when needed, the
    wheel scrolls from anywhere over the page, and a widget that takes the focus is brought into view."""

    def __init__(self, parent):
        super().__init__(parent, bg=BG)
        self.view = tk.Canvas(self, bg=BG, highlightthickness=0, bd=0)
        self.bar = ttk.Scrollbar(self, command=self.view.yview)
        self.view.configure(yscrollcommand=self.bar.set, yscrollincrement=20)
        self.view.pack(side="left", fill="both", expand=True)
        self.body = tk.Frame(self.view, bg=BG)
        self.item = self.view.create_window(0, 0, window=self.body, anchor="nw")
        self.body.bind("<Configure>", self._fit)
        self.view.bind("<Configure>", self._fit)

    def overflows(self):
        return self.body.winfo_reqheight() > self.view.winfo_height()

    def _fit(self, _event=None):
        self.view.itemconfigure(self.item, width=self.view.winfo_width())
        self.view.configure(scrollregion=(0, 0, self.view.winfo_width(), self.body.winfo_reqheight()))
        if self.overflows():
            self.bar.pack(side="right", fill="y", padx=(8, 0))
        else:
            self.bar.pack_forget()
            self.view.yview_moveto(0)

    def wheel(self, event):
        if isinstance(event.widget, str) or not str(event.widget).startswith(str(self)) or not self.overflows():
            return   # (a widget of Tk's own, such as a list that drops down, has no object)
        if event.widget.winfo_class() in ("Listbox", "Text", "TCombobox", "TSpinbox"):
            return   # the widget's own wheel
        up = event.num == 4 or getattr(event, "delta", 0) > 0
        self.view.yview_scroll(-3 if up else 3, "units")

    def reveal(self, event):
        if isinstance(event.widget, str) or not str(event.widget).startswith(str(self.body) + "."):
            return
        if getattr(event.widget, "from_mouse", False):   # (a row the mouse selected stays under it)
            event.widget.from_mouse = False
            return
        top = event.widget.winfo_rooty() - self.body.winfo_rooty()
        bottom = top + event.widget.winfo_height()
        shown, height = self.view.canvasy(0), self.view.winfo_height()
        total = max(1, self.body.winfo_reqheight())
        if top < shown:
            self.view.yview_moveto(max(0, top - 12) / total)
        elif bottom > shown + height:
            self.view.yview_moveto((bottom + 12 - height) / total)


def native_size(root):
    """The primary monitor's resolution in physical pixels (Windows: not the DPI-scaled size Tk reports), or None."""
    if WINDOWS:
        try:
            import ctypes
            user32 = ctypes.windll.user32
            dc = user32.GetDC(0)
            try:
                w, h = ctypes.windll.gdi32.GetDeviceCaps(dc, 118), ctypes.windll.gdi32.GetDeviceCaps(dc, 117)   # DESKTOPHORZRES, DESKTOPVERTRES
            finally:
                user32.ReleaseDC(0, dc)
            if w > 0 and h > 0:
                return w, h
        except (OSError, AttributeError):
            pass
    try:
        return root.winfo_screenwidth(), root.winfo_screenheight()
    except tk.TclError:
        return None
