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
SELECTED = "#2a3480"   # the selected row, while the keys are elsewhere; a button
BLUE, BLUE_D, PINK_D, SHADOW = "#2e5cff", "#1a2f8f", "#8f1f4d", "#0b1240"
HEADING = STRONG = "TkDefaultFont"   # the families of the titles, and of the rows' names (theme)
SCALE = 1.0            # pixels of this screen per pixel of the design (96 DPI)


def px(n):
    return round(n * SCALE)


def sharp_windows():
    """Windows: the process draws at the screen's own resolution instead of being stretched to it (before any window is made)."""
    if WINDOWS:
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)   # PROCESS_SYSTEM_DPI_AWARE: what Tk 8.6 follows
        except (OSError, AttributeError):
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except (OSError, AttributeError):
                pass


def scale_to(root, dpi=None):
    """Sizes and type for the screen's DPI, as far as the smallest window still fits on it."""
    global SCALE
    dpi = dpi or root.winfo_fpixels("1i")
    fits = min(root.winfo_screenwidth() / 900, (root.winfo_screenheight() - 72) / 650)
    SCALE = max(1.0, min(dpi / 96, fits, 4.0))
    root.tk.call("tk", "scaling", SCALE * 96 / 72)   # (type is in points: it follows the same scale)


def theme(root):
    global HEADING, STRONG
    from . import paint   # (it takes its scale from here)
    paint.use(root)
    installed = set(font.families(root))
    body = next((name for name in ("Segoe UI", "Noto Sans", "DejaVu Sans") if name in installed),
                font.nametofont("TkDefaultFont").actual("family"))
    HEADING = next((name for name in ("Barlow Condensed", "Bahnschrift SemiCondensed", "Bahnschrift", "DejaVu Sans Condensed")
                    if name in installed), body)
    STRONG = next((name for name in ("Segoe UI Semibold", "Noto Sans Medium") if name in installed), body)
    for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont"):
        font.nametofont(name).configure(family=body, size=10)
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(".", background=BG, foreground=INK, bordercolor=LINE, font=(body, 10))

    # buttons: leaning bars, each state a picture whose middle is stretched
    high, slant, wide = px(36), px(9), px(60)
    for name, normal, over, words in (("TButton", SELECTED, "#3b49a8", INK), ("Play.TButton", RED, "#ff7fac", BG)):
        bar = lambda colour: paint.leaning(wide, high, slant, colour)
        element = "Liftoff." + name
        style.element_create(element, "image", bar(normal), ("disabled", bar("#1e2558")), ("pressed", bar(CYAN)), ("focus", bar(INK)),
                             ("active", bar(over)), border=(slant + px(4), 0), sticky="ew")
        for kind, ground in ((name, BG), ("Card." + name, PANEL)):   # on the page, on a card
            style.layout(kind, [(element, {"sticky": "ew", "children": [
                ("Button.padding", {"sticky": "nsew", "children": [("Button.label", {"sticky": ""})]})]})])
            style.configure(kind, background=ground, foreground=words, font=(HEADING, 13, "bold italic"), padding=(px(18), px(2)), anchor="center")
            style.map(kind, foreground=[("disabled", DISABLED), ("pressed", BG), ("focus", BG)], background=[])
    style.configure("TEntry", fieldbackground=ENTRY, insertcolor=INK, padding=(px(8), px(5)))
    style.configure("TCombobox", fieldbackground=ENTRY, background=PANEL, arrowcolor=CYAN, arrowsize=px(12), padding=(px(7), px(5)))
    style.map("TCombobox", fieldbackground=[("readonly", ENTRY)], selectbackground=[("readonly", ENTRY)], background=[("active", SELECTED)],
              selectforeground=[("readonly", INK)], foreground=[("readonly", INK)])
    style.configure("TCheckbutton", background=BG, foreground=INK, indicatorbackground=ENTRY, indicatorsize=px(12))
    style.map("TCheckbutton", indicatorbackground=[("selected", CYAN)], background=[("active", BG)], foreground=[("disabled", DISABLED)])
    style.configure("TProgressbar", background=CYAN, troughcolor=ENTRY, thickness=px(12), borderwidth=0, bordercolor=ENTRY, lightcolor=CYAN,
                    darkcolor=CYAN)
    style.layout("Vertical.TScrollbar", [("Vertical.Scrollbar.trough", {"sticky": "ns", "children": [
        ("Vertical.Scrollbar.thumb", {"expand": True, "sticky": "nswe"})]})])   # no arrows
    style.configure("Vertical.TScrollbar", background=LINE, troughcolor=RAIL, bordercolor=BG, lightcolor=LINE, darkcolor=LINE,
                    gripcount=0, width=px(10))
    style.map("Vertical.TScrollbar", background=[("disabled", RAIL), ("pressed", CYAN), ("active", "#5a6bd0")])
    root.option_add("*TCombobox*Listbox.background", ENTRY)
    root.option_add("*TCombobox*Listbox.foreground", INK)
    root.option_add("*TCombobox*Listbox.selectBackground", LINE)
    return body, HEADING


def card(parent, strip=BLUE):
    """A flat card with a strip of colour at its left. Returns it and the frame for what it holds."""
    frame = tk.Frame(parent, bg=PANEL)
    tk.Frame(frame, bg=strip, width=px(6)).pack(side="left", fill="y")
    body = tk.Frame(frame, bg=PANEL)
    body.pack(side="left", fill="both", expand=True, padx=px(18), pady=px(13))
    return frame, body


def headline(parent, text="", size=17, **options):
    """A title, in the menu's type."""
    return label(parent, text, **{"size": size, "font_family": HEADING, "style": "bold italic", **options})


def label(parent, text="", *, color=INK, size=10, bold=False, bg=None, font_family=None, style=None, **options):
    family = font_family or font.nametofont("TkDefaultFont").actual("family")
    # left-aligned unless the caller says otherwise (passing anchor or justify here twice raised a TypeError: the home page did not open)
    return tk.Label(parent, text=text, fg=color, bg=bg or parent.cget("bg"), font=(family, size, style or ("bold" if bold else "normal")),
                    **{"anchor": "w", "justify": "left", **options})


def text_box(parent, height=4):
    return tk.Text(parent, height=height, bg=ENTRY, fg=INK, insertbackground=INK,
                   selectbackground=LINE, highlightthickness=1, highlightbackground=LINE,
                   highlightcolor=CYAN, relief="flat", padx=px(9), pady=px(7), wrap="word",
                   font="TkTextFont", undo=True)


class ScrollPage(tk.Frame):
    """A page that scrolls when the window is shorter than it: `body` takes the widgets. The bar shows only when needed, the
    wheel scrolls from anywhere over the page, and a widget that takes the focus is brought into view."""

    def __init__(self, parent):
        super().__init__(parent, bg=BG)
        self.view = tk.Canvas(self, bg=BG, highlightthickness=0, bd=0)
        self.bar = ttk.Scrollbar(self, command=self.view.yview)
        self.view.configure(yscrollcommand=self.bar.set, yscrollincrement=px(20))
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
            self.bar.pack(side="right", fill="y", padx=(px(8), 0))
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
            self.view.yview_moveto(max(0, top - px(12)) / total)
        elif bottom > shown + height:
            self.view.yview_moveto((bottom + px(12) - height) / total)


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
