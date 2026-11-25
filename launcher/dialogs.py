# Orbitals PC Recomp, a work based on SwitchRecomp by MZ Labs. GNU AGPL v3.0 with the additional terms of NOTICE.txt (LICENSE.txt).
"""Questions and messages inside the window they belong to: the keyboard and a controller answer them, and they show in Steam's Gaming
Mode, where a window of their own may not. Each returns when it is answered."""

import tkinter as tk
from tkinter import ttk

from .look import BG, BLUE_D, CYAN, ENTRY, INK, LINE, MUTED, RED, SHADOW, headline, label, px

open_dialogs = []   # the innermost last


def toward(widget, x, y, inside):
    """Give the focus to the nearest widget in a direction. Returns whether there was one."""
    def middle(w):
        return w.winfo_rootx() + w.winfo_width() / 2, w.winfo_rooty() + w.winfo_height() / 2

    def places(w):
        for child in w.winfo_children():
            if child.winfo_class() == "Toplevel":
                continue
            takes = str(child.cget("takefocus")) if "takefocus" in child.keys() else ""
            plain = child.winfo_class() in ("TButton", "Entry", "TEntry", "TCombobox", "TCheckbutton", "Text", "Listbox")
            off = child.instate(["disabled"]) if isinstance(child, ttk.Widget) else False
            if child.winfo_ismapped() and not off and (takes == "1" or plain and takes != "0"):
                yield child
            yield from places(child)

    cx, cy = middle(widget)
    best = None
    for place in places(inside):
        if place is widget:
            continue
        dx, dy = middle(place)[0] - cx, middle(place)[1] - cy
        ahead, aside = (dx * x, abs(dy)) if x else (dy * y, abs(dx))
        if x and aside > max(place.winfo_height(), widget.winfo_height()):   # left and right stay in the row
            continue
        if ahead > 3 and (best is None or ahead + aside < best[0]):
            best = (ahead + aside, place)
    if best:
        best[1].focus_set()
    return best is not None


class Dialog:
    """A card in the middle of the window, over everything else. `labels`: its buttons, the first the usual answer."""

    def __init__(self, parent, title, text, labels, alarm=False, value=None, check=None):
        window = parent.winfo_toplevel()
        self.answer, self.check, self.entry = None, check, None
        self.cover = tk.Frame(window, bg=BLUE_D, takefocus=0)
        self.cover.place(x=0, y=0, relwidth=1, relheight=1)
        shadow = tk.Frame(self.cover, bg=SHADOW)   # hard, like the title screen's card's
        card = tk.Frame(self.cover, bg=BG)
        card.place(relx=0.5, rely=0.46, anchor="center")
        card.bind("<Configure>", lambda e: shadow.place(relx=0.5, rely=0.46, x=px(9), y=px(9), anchor="center", width=e.width, height=e.height))
        tk.Frame(card, bg=RED if alarm else CYAN, width=px(7)).pack(side="left", fill="y")
        body = tk.Frame(card, bg=BG)
        body.pack(side="left", padx=px(24), pady=px(20))
        headline(body, title, size=20, wraplength=px(520)).pack(anchor="w")
        tk.Frame(body, bg=BG, width=px(420), height=px(6)).pack()
        label(body, text, color=INK if value is None else MUTED, wraplength=px(520)).pack(anchor="w")
        if value is not None:
            self.entry = tk.Entry(body, bg=ENTRY, fg=INK, insertbackground=INK, relief="flat", highlightthickness=px(2),
                                  highlightbackground=LINE, highlightcolor=CYAN, font="TkTextFont")
            self.entry.insert(0, value)
            self.entry.select_range(0, "end")
            self.entry.pack(fill="x", pady=(px(8), 0), ipady=px(5))
        self.error = label(body, "", color=RED, wraplength=px(520))
        self.error.pack(anchor="w")
        row = tk.Frame(body, bg=BG)
        row.pack(anchor="w", pady=(px(8), 0))
        self.buttons = []
        for number, text in enumerate(labels):
            button = ttk.Button(row, text=text.upper(), command=lambda n=number: self.take(n), style="Play.TButton" if not number and not alarm else "TButton")
            button.pack(side="left", padx=(0, px(8)))
            button.bind("<Return>", lambda e, n=number: self.take(n))
            for key, x, y in (("<Left>", -1, 0), ("<Right>", 1, 0), ("<Up>", 0, -1), ("<Down>", 0, 1)):
                button.bind(key, lambda e, x=x, y=y: self.go(e.widget, x, y))
            self.buttons.append(button)
        if self.entry:
            self.entry.bind("<Return>", lambda e: self.take(0))
            self.entry.bind("<Down>", lambda e: self.go(self.entry, 0, 1))
        self.seal(self.cover)
        before = None
        try:
            before = window.focus_get()
        except KeyError:
            pass
        grabbed = window.grab_current()
        open_dialogs.append(self)
        self.refocus()
        self.cover.grab_set()
        try:
            self.cover.wait_window()
        finally:
            open_dialogs.remove(self)
        try:
            if grabbed and grabbed.winfo_exists():
                grabbed.grab_set()
            if before and before.winfo_exists():
                before.focus_set()
        except tk.TclError:   # the window was closed meanwhile
            pass

    def refocus(self):
        """Also when the page under the dialog was built again."""
        if self.cover.winfo_exists():
            (self.entry or self.buttons[0]).focus_set()

    def seal(self, widget):
        """Nothing under the dialog gets its keys: not through the window's own bindings either."""
        widget.bindtags((str(widget), widget.winfo_class(), "all"))
        widget.bind("<Escape>", lambda e: self.close())
        for child in widget.winfo_children():
            self.seal(child)

    def go(self, widget, x, y):
        toward(widget, x, y, self.cover)
        return "break"

    def take(self, number):
        if number == 0 and self.entry is not None:
            value = self.entry.get()
            if self.check:
                try:
                    self.check(value)
                except ValueError as error:
                    self.error.configure(text=str(error))
                    return "break"
            self.answer = value
        else:
            self.answer = number
        self.cover.destroy()
        return "break"

    def close(self):
        self.answer = None
        self.cover.destroy()
        return "break"


def message(parent, title, text):
    Dialog(parent, title, text, ("OK",))


def error(parent, title, text):
    Dialog(parent, title, text, ("OK",), alarm=True)


def confirm(parent, title, text, yes="Yes", no="Cancel", alarm=False):
    return Dialog(parent, title, text, (yes, no), alarm=alarm).answer == 0


def choose(parent, title, text, labels):
    """The number of the answer taken, or None."""
    return Dialog(parent, title, text, labels).answer


def ask_text(parent, title, text, value="", check=None):
    """What was typed, or None. check(value) raises ValueError for what cannot be taken: said in the dialog."""
    answer = Dialog(parent, title, text, ("OK", "Cancel"), value=value, check=check).answer
    return answer if isinstance(answer, str) else None
