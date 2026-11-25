# Orbitals PC Recomp, a work based on SwitchRecomp by MZ Labs. GNU AGPL v3.0 with the additional terms of NOTICE.txt (LICENSE.txt).
"""The rows of a settings page: a label and its value on the left, what the selected row does on the right.

Every row is one widget for the mouse, the keyboard and a controller: up and down go from row to row, left and right change the
value, Enter takes the next one. A value is saved as soon as it changes; the caller's `get` and `set` know where."""

import tkinter as tk

from .look import BG, CYAN, DISABLED, ENTRY, INK, LINE, MUTED, PANEL, PEACH, RAIL, RED, SELECTED, label, px


class Row(tk.Frame):
    """One row. `describe` is its text for the description pane (a string or a function); `enabled` a function."""

    def __init__(self, rows, caption, describe, *, indent=False, enabled=None):
        super().__init__(rows.page, bg=PANEL, highlightthickness=px(2), highlightbackground=BG, highlightcolor=CYAN, takefocus=1)
        self.rows, self.caption, self.describe = rows, caption, describe
        self.is_enabled = enabled or (lambda: True)
        self.on = True
        self.pack(fill="x", padx=(px(26) if indent else 0, 0), pady=(0, px(2)))
        self.name = label(self, caption, bg=PANEL)
        self.name.pack(side="left", padx=(px(12), 0), pady=px(9))
        self.dot = label(self, "", bg=PANEL, color=RED)   # "•": not the default value
        self.dot.pack(side="left", padx=px(6))
        for key, handler in (("<Up>", lambda e: self.step(-1)), ("<Down>", lambda e: self.step(1)),
                             ("<Left>", lambda e: self.move(-1)), ("<Right>", lambda e: self.move(1)),
                             ("<Return>", lambda e: self.press()), ("<space>", lambda e: self.press())):
            self.bind(key, handler)
        self.bind("<FocusIn>", lambda e: self.rows.select(self))
        self.bind("<Button-1>", lambda e: self.by_hand())
        self.name.bind("<Button-1>", lambda e: self.by_hand())
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

    def paint(self, ground):
        for widget in (self, *self.winfo_children()):
            if not isinstance(widget, (tk.Entry, tk.Button)):
                widget.configure(bg=ground)

    def sync(self):
        """Show the state as it is now."""
        self.on = bool(self.is_enabled())
        self.name.configure(fg=INK if self.on else DISABLED)
        self.configure(takefocus=1 if self.on else 0)


class ChoiceRow(Row):
    """A value out of `values` (a list, or a function giving one), shown through `show`."""

    def __init__(self, rows, caption, values, get, set_, describe, *, show=str, default=None, other=None, **options):
        super().__init__(rows, caption, describe, **options)
        self.values, self.get, self.set, self.show, self.default, self.other = values, get, set_, show, default, other
        self.later = label(self, "▶", bg=PANEL, color=CYAN, cursor="hand2")
        self.later.pack(side="right", padx=(px(2), px(10)), fill="y")
        self.value = label(self, "", bg=PANEL, anchor="center", cursor="hand2", justify="center")
        self.value.pack(side="right", fill="y")
        self.earlier = label(self, "◀", bg=PANEL, color=CYAN, cursor="hand2")
        self.earlier.pack(side="right", padx=px(2), fill="y")
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
        self.value.configure(text=self.show(value), fg=INK if self.on else DISABLED,
                             width=min(30, max(len(self.show(choice)) for choice in choices) + 1))
        self.earlier.configure(fg=CYAN if self.on and choices.index(value) > 0 else LINE)
        self.later.configure(fg=CYAN if self.on and choices.index(value) < len(choices) - 1 else LINE)
        changed = self.on and self.default is not None and value != self.default[0]
        self.dot.configure(text="•" if changed else "")


def switch(rows, caption, get, set_, describe, *, default=None, **options):
    """An On / Off row."""
    return ChoiceRow(rows, caption, (False, True), get, set_, describe, show=lambda v: "On" if v else "Off", default=default, **options)


class ActionRow(Row):
    """A row that does something: the whole of it is the button. `text` is what stands at its right, or a function."""

    def __init__(self, rows, caption, text, run, describe, **options):
        super().__init__(rows, caption, describe, **options)
        self.text, self.run = text, run
        self.button = label(self, "", bg=PANEL, color=CYAN, cursor="hand2", anchor="e", justify="right")
        self.button.pack(side="right", padx=(px(8), px(12)), fill="y")
        self.configure(cursor="hand2"); self.name.configure(cursor="hand2")
        for widget in (self, self.name, self.button):
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
        self.button.configure(text=self.text() if callable(self.text) else self.text, fg=CYAN if self.on else DISABLED)


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
        self.entry.pack(fill="x", padx=px(12), pady=(0, px(4)), ipady=px(4))
        self.error = label(self, "", bg=PANEL, color=PEACH, size=9)
        self.error.pack(fill="x", padx=px(12), pady=(0, px(6)))
        self.configure(takefocus=0)
        self.entry.bind("<Up>", lambda e: self.step(-1)); self.entry.bind("<Down>", lambda e: self.step(1))
        self.entry.bind("<Return>", lambda e: self.keep())
        self.entry.bind("<FocusOut>", lambda e: self.keep())
        self.entry.bind("<FocusIn>", lambda e: self.rows.select(self))

    def by_hand(self):
        self.entry.focus_set()

    def hovered(self):
        pass

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
        self.pane = tk.Frame(side, bg=BG)
        self.pane.pack(fill="both", expand=True, pady=(px(4), 0))
        width = px(280)
        self.title = label(self.pane, "", size=13, bold=True, font_family=app.heading_font, wraplength=width)
        self.title.pack(fill="x")
        self.text = label(self.pane, "", color=MUTED, wraplength=width)
        self.text.pack(fill="x", pady=(px(6), 0))
        self.note = label(self.pane, "", color=PEACH, wraplength=width)
        self.note.pack(fill="x", pady=(px(10), 0))

    def group(self, title):
        label(self.page, title, color=CYAN, bold=True).pack(anchor="w", pady=(px(10) if self.items else 0, px(5)))

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

    def show(self):
        for row in self.items:
            row.paint(SELECTED if row is self.selected else PANEL)
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
