# Orbitals PC Recomp, a work based on SwitchRecomp by MZ Labs. GNU AGPL v3.0 with the additional terms of NOTICE.txt (LICENSE.txt).
"""The rows of a settings page: a label and its value on the left, what the selected row does on the right.

Every row is one widget for the mouse, the keyboard and a controller: up and down go from row to row, left and right change the
value, Enter takes the next one. A value is saved as soon as it changes; the caller's `get` and `set` know where."""

import tkinter as tk

from . import look, paint
from .look import BG, BLUE, BLUE_D, CYAN, DISABLED, ENTRY, INK, LINE, MUTED, PANEL, PEACH, PINK_D, RAIL, RED, SELECTED, headline, label, px

OFF = "#10143a"   # a row that cannot be used now


class Row(tk.Frame):
    """One row. `describe` is its text for the description pane (a string or a function); `enabled` a function."""

    def __init__(self, rows, caption, describe, *, indent=False, enabled=None):
        super().__init__(rows.page, bg=BG, takefocus=1, highlightthickness=0)
        self.rows, self.caption, self.describe = rows, caption, describe
        self.is_enabled = enabled or (lambda: True)
        self.on, self.chosen, self.keyed, self.dressed = True, False, False, None
        self.pack(fill="x", padx=(px(26) if indent else 0, 0), pady=(0, px(4)))
        self.back = tk.Label(self, bd=0, bg=BG, anchor="nw", padx=0, pady=0)   # its leaning bar, under everything
        self.back.place(x=0, y=0, relwidth=1, relheight=1)
        self.name = label(self, caption, font_family=look.STRONG)
        self.name.pack(side="left", padx=(px(30), 0), pady=px(9))
        self.dot = label(self, "", color=PEACH, bold=True)   # "•": not the default value
        self.dot.pack(side="left", padx=px(6))
        self.bind("<Configure>", lambda e: self.dress(True))
        for key, handler in (("<Up>", lambda e: self.step(-1)), ("<Down>", lambda e: self.step(1)),
                             ("<Left>", lambda e: self.move(-1)), ("<Right>", lambda e: self.move(1)),
                             ("<Return>", lambda e: self.press()), ("<space>", lambda e: self.press())):
            self.bind(key, handler)
        self.bind("<FocusIn>", lambda e: self.rows.select(self))
        self.bind("<FocusOut>", lambda e: self.after_idle(self.rows.show_focus))
        for widget in (self, self.back, self.name):
            widget.bind("<Button-1>", lambda e: self.by_hand())
        self.bind("<Enter>", lambda e: self.hovered())

    def by_hand(self):
        self.from_mouse = self.focus_get() is not self
        self.focus_set()

    def hovered(self):
        """The mouse selects a row like the keyboard does, unless the player is typing somewhere."""
        try:
            typing = isinstance(self.focus_get(), tk.Entry)
        except KeyError:
            return
        if self.on and not typing and self.focus_displayof() is not None:
            self.by_hand()

    def step(self, direction):
        self.rows.step(self, direction)
        return "break"

    def move(self, direction):
        return "break"

    def press(self):
        return "break"

    def dress(self, again=False):
        """Its bar and its colours: the selected row is the title screen's white bar, while the keys are on it."""
        w, h = self.winfo_width(), self.winfo_height()
        state = (w, h, self.on, self.chosen, self.keyed)
        if h < 8 or (state == self.dressed and not again):
            return
        self.dressed = state
        lit = self.chosen and self.keyed and self.on
        ground = INK if lit else SELECTED if self.chosen and self.on else PANEL if self.on else OFF
        self.back.configure(image=paint.leaning(w, h, px(9), ground, px(7) if lit else 0, RED))
        words = PINK_D if lit else INK if self.on else DISABLED
        for widget in self.winfo_children():
            if widget is not self.back and not isinstance(widget, (tk.Entry, tk.Menu)):
                widget.configure(bg=ground)
        self.name.configure(fg=words)
        self.dot.configure(fg=RED if lit else PEACH)
        self.tint(lit)

    def tint(self, lit):
        """The colours of what stands at its right."""

    def sync(self):
        """Show the state as it is now."""
        self.on = bool(self.is_enabled())
        self.configure(takefocus=1 if self.on else 0)
        self.dress()


class ChoiceRow(Row):
    """A value out of `values` (a list, or a function giving one), shown through `show`."""

    def __init__(self, rows, caption, values, get, set_, describe, *, show=str, default=None, other=None, **options):
        super().__init__(rows, caption, describe, **options)
        self.values, self.get, self.set, self.show, self.default, self.other = values, get, set_, show, default, other
        self.later = label(self, cursor="hand2", width=px(24), image=paint.shape("next", px(14), CYAN), anchor="center")
        self.later.pack(side="right", padx=(0, px(16)))
        self.value = label(self, "", anchor="center", cursor="hand2", justify="center", bold=True)
        self.value.pack(side="right")
        self.earlier = label(self, cursor="hand2", width=px(24), image=paint.shape("before", px(14), CYAN), anchor="center")
        self.earlier.pack(side="right")
        self.earlier.bind("<Button-1>", lambda e: (self.by_hand(), self.move(-1)))
        self.later.bind("<Button-1>", lambda e: (self.by_hand(), self.move(1)))
        self.value.bind("<Button-1>", lambda e: (self.by_hand(), self.listed()))

    def choices(self):
        choices = list(self.values() if callable(self.values) else self.values)
        return choices if self.get() in choices else [self.get(), *choices]   # a value of its own, e.g. from the in-game settings

    def take(self, value):
        if self.on and value != self.get():
            self.rows.app.action(lambda: self.set(value))
        self.rows.sync()
        return "break"

    def move(self, direction):
        choices = self.choices()
        return self.take(choices[max(0, min(len(choices) - 1, choices.index(self.get()) + direction))])

    def press(self):
        choices = self.choices()
        return self.take(choices[(choices.index(self.get()) + 1) % len(choices)])

    def listed(self):
        """The whole list, under the mouse."""
        if not self.on:
            return
        menu = tk.Menu(self, tearoff=False, bg=ENTRY, fg=INK, activebackground=LINE, activeforeground=INK, bd=0)
        chosen = tk.StringVar(menu, self.show(self.get()))
        for value in self.choices():
            menu.add_radiobutton(label=self.show(value), value=self.show(value), variable=chosen, selectcolor=CYAN,
                                 command=lambda v=value: self.take(v))
        if self.other:
            menu.add_separator()
            menu.add_command(label=self.other[0], command=lambda: (self.other[1](), self.rows.sync()))
        try:
            menu.tk_popup(self.value.winfo_rootx(), self.value.winfo_rooty() + self.value.winfo_height())
        finally:
            menu.grab_release()

    def sync(self):
        super().sync()
        choices, value = self.choices(), self.get()
        # (wide enough for the widest value, so the arrows stay under the pointer)
        self.value.configure(text=self.show(value), width=min(30, max(len(self.show(choice)) for choice in choices) + 1))
        self.tint(self.chosen and self.keyed and self.on)
        changed = self.on and self.default is not None and value != self.default[0]
        self.dot.configure(text="•" if changed else "")


    def tint(self, lit):
        choices, value = self.choices(), self.get()
        at = choices.index(value)
        self.value.configure(fg=BLUE_D if lit else INK if self.on else DISABLED)
        for arrow, kind, can in ((self.earlier, "before", at > 0), (self.later, "next", at < len(choices) - 1)):
            colour = (RED if lit else CYAN) if self.on and can else ("#d9d3ea" if lit else LINE if self.on else "#1c2352")
            arrow.configure(image=paint.shape(kind, px(14), colour))


def switch(rows, caption, get, set_, describe, *, default=None, **options):
    """An On / Off row."""
    return ChoiceRow(rows, caption, (False, True), get, set_, describe, show=lambda v: "On" if v else "Off", default=default, **options)


class ActionRow(Row):
    """A row that does something: the whole of it is the button. `text` is what stands at its right, or a function."""

    def __init__(self, rows, caption, text, run, describe, **options):
        super().__init__(rows, caption, describe, **options)
        self.text, self.run = text, run
        self.button = headline(self, "", size=13, color=CYAN, cursor="hand2", anchor="e", justify="right")
        self.button.pack(side="right", padx=(px(8), px(22)))
        for widget in (self, self.back, self.name):
            widget.configure(cursor="hand2")
        for widget in (self, self.back, self.name, self.button):
            widget.bind("<ButtonRelease-1>", self.released)

    def released(self, event):
        x, y = event.x_root - self.winfo_rootx(), event.y_root - self.winfo_rooty()
        if 0 <= x < self.winfo_width() and 0 <= y < self.winfo_height():
            self.press()

    def press(self):
        if self.on:
            self.rows.app.action(self.run)
            if self.winfo_exists():
                self.rows.sync()
        return "break"

    def sync(self):
        super().sync()
        self.button.configure(text=(self.text() if callable(self.text) else self.text).upper())
        self.tint(self.chosen and self.keyed and self.on)

    def tint(self, lit):
        self.button.configure(fg=RED if lit else CYAN if self.on else DISABLED)


class TextRow(Row):
    """A row with a text field. `set_` raises LauncherError for a value it refuses: said under the field."""

    def __init__(self, rows, caption, get, set_, describe, **options):
        super().__init__(rows, caption, describe, **options)
        self.get, self.set = get, set_
        self.name.pack_configure(side="top", anchor="w", pady=(px(8), px(3)))
        self.dot.pack_forget()
        self.entry = tk.Entry(self, bg=ENTRY, fg=INK, insertbackground=INK, relief="flat", highlightthickness=px(2),
                              highlightbackground=LINE, highlightcolor=CYAN, disabledbackground=RAIL, disabledforeground=DISABLED,
                              font="TkTextFont")
        self.entry.pack(fill="x", padx=(px(30), px(20)), pady=(0, px(4)), ipady=px(4))
        self.error = label(self, "", color=PEACH, size=9)
        self.error.pack(anchor="w", padx=(px(30), px(20)), pady=(0, px(6)))
        self.configure(takefocus=0)
        self.entry.bind("<Up>", lambda e: self.step(-1)); self.entry.bind("<Down>", lambda e: self.step(1))
        self.entry.bind("<Return>", lambda e: self.keep())
        self.entry.bind("<FocusOut>", lambda e: (self.keep(), self.after_idle(self.rows.show_focus)))
        self.entry.bind("<FocusIn>", lambda e: self.rows.select(self))

    def by_hand(self):
        self.entry.focus_set()

    def hovered(self):
        pass

    def tint(self, lit):
        self.error.configure(fg=PINK_D if lit else PEACH)

    def keep(self):
        if not self.on or self.entry.get().strip() == self.get():
            self.error.configure(text="")
            return
        try:
            self.set(self.entry.get().strip())
            self.error.configure(text="")
        except (ValueError, OSError) as error:   # (LauncherError is a ValueError)
            self.error.configure(text=str(error))

    def sync(self):
        super().sync()
        self.configure(takefocus=0)
        if self.focus_get() is not self.entry and not self.error.cget("text"):
            self.entry.configure(state="normal")
            self.entry.delete(0, "end"); self.entry.insert(0, self.get())
        self.entry.configure(state="normal" if self.on else "disabled")


class Rows:
    """The rows of a page (into app.page) and its description pane (into `side`)."""

    def __init__(self, app, side):
        self.app, self.page, self.items, self.selected = app, app.page, [], None
        strip = tk.Frame(side, bg=BLUE, width=px(5))
        strip.pack(side="left", fill="y", pady=(px(4), px(8)))
        self.pane = tk.Frame(side, bg=BG)
        self.pane.pack(side="left", fill="both", expand=True, padx=(px(16), 0), pady=(px(2), 0))
        width = px(262)
        self.title = headline(self.pane, "", size=19, wraplength=width)
        self.title.pack(fill="x")
        self.text = label(self.pane, "", color=MUTED, wraplength=width)
        self.text.pack(fill="x", pady=(px(6), 0))
        self.note = label(self.pane, "", color=PEACH, wraplength=width)
        self.note.pack(fill="x", pady=(px(10), 0))

    def group(self, title):
        headline(self.page, title.upper(), size=14, color=CYAN).pack(anchor="w", pady=(px(8) if self.items else 0, px(3)))

    def add(self, row):
        self.items.append(row)
        return row

    def choice(self, *args, **options):
        return self.add(ChoiceRow(self, *args, **options))

    def switch(self, *args, **options):
        return self.add(switch(self, *args, **options))

    def action(self, *args, **options):
        return self.add(ActionRow(self, *args, **options))

    def entry(self, *args, **options):
        return self.add(TextRow(self, *args, **options))

    def ready(self):
        """All rows are there: show their state and select the first."""
        self.sync()
        first = next((row for row in self.items if row.on), None)
        if first:
            first.focus_set()
            self.select(first)

    def choose(self, caption):
        """The row of this caption, if it can be chosen."""
        row = next((row for row in self.items if row.caption == caption and row.on), None)
        if row:
            (row.entry if isinstance(row, TextRow) else row).focus_set()
            self.select(row)

    def step(self, row, direction):
        places = [item for item in self.items if item.on]
        if row in places:
            at = places.index(row) + direction
            if 0 <= at < len(places):
                target = places[at]
                (target.entry if isinstance(target, TextRow) else target).focus_set()
            elif at < 0:
                self.app.focus_header()

    def select(self, row):
        self.selected = row
        self.show()

    def show_focus(self):
        """Which row is selected, and whether the keys are on it."""
        try:
            focus = self.page.focus_get()
        except (KeyError, tk.TclError):   # (a native dialog's; the page is gone)
            return
        for row in self.items:
            if row.winfo_exists():
                row.chosen, row.keyed = row is self.selected, focus is row or focus is getattr(row, "entry", self)
                row.dress()

    def show(self):
        self.show_focus()
        if self.selected:
            text = self.selected.describe
            text = text() if callable(text) else text
            text, note = text if isinstance(text, tuple) else (text, "")
            self.title.configure(text=self.selected.caption)
            self.text.configure(text=text)
            self.note.configure(text=note)

    def sync(self):
        for row in self.items:
            row.sync()
        self.show()
