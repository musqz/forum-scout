# Forum Scout — GTK3 → GTK4 Migration Plan

## Context

Port `forum-scout.py` (GTK3, ~1540 lines) to GTK4.
Backend logic is unchanged. Only the UI layer is rewritten.
Source repo: `forum-scout-gtk4` on GitHub.
Reference file: original `forum-scout.py` (GTK3).

## Architecture decision

Keep everything in one file (`forum-scout.py`) for now.
Entry point changes from `Gtk.main()` to `Gtk.Application`.
All backend code (fetchers, suggesters, i18n, file I/O) is copied verbatim — do not touch it.

---

## GTK3 → GTK4 API mapping (reference for all steps)

| GTK3 | GTK4 replacement |
|---|---|
| `gi.require_version("Gtk", "3.0")` | `gi.require_version("Gtk", "4.0")` |
| `Gtk.Window` | `Gtk.ApplicationWindow` |
| `Gtk.main()` / `Gtk.main_quit()` | `Gtk.Application` + `app.run()` |
| `Gtk.ListStore` + `GtkTreeView` | `Gtk.ColumnView` + `Gio.ListStore` + `Gtk.SignalListItemFactory` |
| `Gtk.CellRendererText` | `Gtk.Label` inside factory |
| `GtkTreeViewColumn` | `Gtk.ColumnViewColumn` |
| `get_selection()` | `Gtk.MultiSelection` or `Gtk.SingleSelection` |
| `Gtk.Clipboard.get()` | `widget.get_clipboard()` |
| `key-press-event` | `Gtk.EventControllerKey` |
| `button-press-event` | `Gtk.GestureClick` |
| `motion-notify-event` | `Gtk.EventControllerMotion` |
| `Gtk.StatusBar` | `Gtk.Label` (plain, in a box) |
| `Gtk.Menu` (context menu) | `Gtk.PopoverMenu` + `Gio.Menu` |
| `cb.store()` (clipboard) | not needed in GTK4 |
| `self.set_border_width()` | use margins on child widgets |
| `widget.show_all()` | not needed — GTK4 shows by default |
| `Gtk.Box.pack_start()` | `box.append(widget)` |
| `Gtk.ScrolledWindow.add()` | `sw.set_child(widget)` |
| `Gtk.Popover.new(btn)` + `pop.add()` + `pop.popup()` | `Gtk.Popover` + `pop.set_child()` + `pop.popup()` |
| `Gtk.FlowBox` | unchanged |
| `Gtk.Notebook` | unchanged |
| `Gtk.SearchEntry` | unchanged |
| `Gtk.SpinButton` | unchanged |
| `Gtk.Spinner` | unchanged |

---

## Step 0 — Repo setup

```
forum-scout-gtk4/
├── forum-scout.py        ← new GTK4 version (built incrementally)
├── forums.conf           ← copy from GTK3 repo unchanged
├── translations/         ← copy from GTK3 repo unchanged
├── VERSION               ← copy from GTK3 repo unchanged
└── PLAN-gtk4.md          ← this file
```

Copy from GTK3 repo verbatim (no changes):
- All fetcher functions (`_fetch_discourse`, `_fetch_mediawiki`, `_fetch_ddg`)
- All suggester functions (`_suggest_discourse`, `_suggest_mediawiki`)
- `_load_forums()`, `FORUMS`, `_FORUM_COLOR`
- `_load_translation()`, `S`, `_EN_STRINGS`
- `_fmt_date()`, `_ForumUnreachable`, `_NET_ERRORS`
- `_DDGParser` class
- `_session` HTTP session
- All constants (`CACHE_DIR`, `BOOKMARK_FILE`, `HISTORY_FILE`, `CONFIG_DIR`, `SETTINGS_FILE`, `APP_TITLE`, `DEFAULT_HITS`, `_VERSION`, `_SEED_TERMS`, `_SUGGEST_*`)

---

## Step 1 — Application skeleton

**Goal:** bare GTK4 app window that opens and closes cleanly.

Replace:
```python
# GTK3
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gtk, Gdk, GLib, Pango

class ScoutWindow(Gtk.Window):
    def __init__(self):
        super().__init__(title=APP_TITLE)
        ...
        self.connect("destroy", Gtk.main_quit)
        self.show_all()

if __name__ == "__main__":
    GLib.set_prgname("forum-scout")
    win = ScoutWindow()
    Gtk.main()
```

With:
```python
# GTK4
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gtk, Gdk, GLib, Pango, Gio

class ScoutWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title=APP_TITLE)
        self.set_default_size(820, 520)
        self.set_size_request(700, 300)
        self._build_ui()
        self._load_settings()
        self._setup_controllers()   # key/click/motion — see Step 5
        self.present()

def on_activate(app):
    win = ScoutWindow(app)

if __name__ == "__main__":
    GLib.set_prgname("forum-scout")
    app = Gtk.Application(application_id="org.musqz.forum-scout")
    app.connect("activate", on_activate)
    app.run(None)
```

**Test:** window opens, closes, no errors.

---

## Step 2 — Top bar (search entry + forums bar)

**Goal:** search entry, Search button, spinner, forums toggle, help button, forums checkboxes all working.

Changes:
- `Gtk.Box.pack_start(w, expand, fill, padding)` → `box.append(w)` (GTK4 has no pack_start)
- `bar.set_border_width(n)` → set `margin_top`, `margin_bottom` etc. on the box itself
- `show_all()` calls → remove entirely (GTK4 shows widgets by default)
- `widget.hide()` / `widget.show()` → `widget.set_visible(False/True)` — same, still works
- `Gtk.CheckButton` + `cb.add(lbl)` → `Gtk.CheckButton(label=...)` or use `set_child(lbl)` (GTK4 deprecates `add()`)
- Everything else in `_build_topbar()` is structurally identical

Specific fix for colored forum labels in checkboxes:
```python
# GTK3: cb.add(lbl) with markup
# GTK4:
cb = Gtk.CheckButton()
lbl = Gtk.Label()
lbl.set_markup(f'<span foreground="{f["color"]}" weight="bold">{f["name"]}</span>')
cb.set_child(lbl)
```

**Test:** forums bar toggles, checkboxes respond, search button clickable.

---

## Step 3 — Results tab (ColumnView)

**Goal:** results display with Forum (colored), Title, Date columns. Sortable. Multi-select. Double-click opens URL.

This is the biggest change. `GtkTreeView` + `GtkListStore` → `GtkColumnView` + `Gio.ListStore`.

### Data model

```python
class ResultItem(GObject.Object):
    __gtype_name__ = "ResultItem"
    def __init__(self, idx, forum, color, title, link, date):
        super().__init__()
        self.idx   = idx
        self.forum = forum
        self.color = color
        self.title = title
        self.link  = link
        self.date  = date
```

### Store + selection

```python
self._res_store = Gio.ListStore(item_type=ResultItem)
selection = Gtk.MultiSelection(model=self._res_store)
cv = Gtk.ColumnView(model=selection)
self._res_view = cv
```

### Factory pattern (one per column)

```python
def _make_factory(attr, colored=False):
    factory = Gtk.SignalListItemFactory()
    def setup(f, item):
        item.set_child(Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END))
    def bind(f, item):
        obj = item.get_item()
        lbl = item.get_child()
        text = getattr(obj, attr)
        if colored:
            lbl.set_markup(f'<span foreground="{obj.color}">{GLib.markup_escape_text(text)}</span>')
        else:
            lbl.set_label(text)
    factory.connect("setup", setup)
    factory.connect("bind", bind)
    return factory
```

### Columns

```python
cv.append_column(Gtk.ColumnViewColumn(title=S["col_n"],     factory=_make_factory("idx"),   fixed_width=28))
cv.append_column(Gtk.ColumnViewColumn(title=S["col_forum"], factory=_make_factory("forum",  colored=True), fixed_width=150))
cv.append_column(Gtk.ColumnViewColumn(title=S["col_title"], factory=_make_factory("title"), expand=True))
cv.append_column(Gtk.ColumnViewColumn(title=S["col_date"],  factory=_make_factory("date"),  fixed_width=100))
```

### Sorting

```python
# Attach a Gtk.CustomSorter to each sortable column
date_sorter = Gtk.CustomSorter.new(lambda a, b, _: (a.date < b.date) - (a.date > b.date), None)
date_col.set_sorter(date_sorter)
```

### Populating results

Replace all `self._res_store.append([...])` with:
```python
self._res_store.append(ResultItem(idx, forum, color, title, link, date))
```

### Double-click / activation

```python
cv.connect("activate", self._on_result_activate)
# activate passes row index, not TreePath:
def _on_result_activate(self, cv, position):
    item = self._res_store.get_item(position)
    self._open_url(item.link)
```

**Test:** search runs, results populate, columns sort, double-click opens browser.

---

## Step 4 — Bookmarks and History tabs

**Goal:** both tabs ported to ColumnView with the same factory pattern as Step 3.

### Bookmark model

```python
class BookmarkItem(GObject.Object):
    __gtype_name__ = "BookmarkItem"
    def __init__(self, forum, title, link, date, color):
        super().__init__()
        self.forum = forum
        self.title = title
        self.link  = link
        self.date  = date
        self.color = color
```

### History model

```python
class HistoryItem(GObject.Object):
    __gtype_name__ = "HistoryItem"
    def __init__(self, time, query):
        super().__init__()
        self.time  = time
        self.query = query
```

Both use `Gtk.MultiSelection` (bookmarks) and `Gtk.SingleSelection` (history).

Bookmark filter entry (`_bm_filter_entry`) — use `Gtk.FilterListModel` wrapping the store:
```python
self._bm_filter  = Gtk.CustomFilter.new(self._bm_filter_fn, None)
filtered = Gtk.FilterListModel(model=self._bm_store, filter=self._bm_filter)
selection = Gtk.MultiSelection(model=filtered)
```

Filter function:
```python
def _bm_filter_fn(self, item, _):
    term = self._bm_filter_entry.get_text().lower()
    if not term:
        return True
    return term in item.title.lower() or term in item.forum.lower()
```

Trigger on entry change:
```python
self._bm_filter_entry.connect("changed", lambda *_: self._bm_filter.changed(Gtk.FilterChange.DIFFERENT))
```

**Test:** bookmarks load, filter works, history loads, re-run search works.

---

## Step 5 — Event controllers (keyboard + mouse)

**Goal:** all keyboard shortcuts working. Right-click context menu on results. Hover link in statusbar.

### Keyboard

```python
key_ctrl = Gtk.EventControllerKey()
key_ctrl.connect("key-pressed", self._on_key_press)
self.add_controller(key_ctrl)
```

Signature change:
```python
# GTK3
def _on_key_press(self, widget, event):
    key  = event.keyval
    ctrl = event.state & Gdk.ModifierType.CONTROL_MASK

# GTK4
def _on_key_press(self, ctrl, keyval, keycode, state):
    key  = keyval
    ctrl = state & Gdk.ModifierType.CONTROL_MASK
```

All the key logic inside stays identical — only the signature and how you read `key`/`ctrl` changes.

### Right-click context menu

```python
# GTK3: button-press-event → Gtk.Menu
# GTK4: GtkGestureClick → Gtk.PopoverMenu

gesture = Gtk.GestureClick(button=3)   # button=3 = right click
gesture.connect("pressed", self._on_result_rclick)
self._res_view.add_controller(gesture)
```

Build the menu with `Gio.Menu` + actions:
```python
menu = Gio.Menu()
menu.append(S["ctx_open"],      "win.open-result")
menu.append(S["ctx_copy"],      "win.copy-result")
menu.append(S["ctx_bm"],        "win.bookmark-result")

pop = Gtk.PopoverMenu(menu_model=menu)
pop.set_parent(self._res_view)
pop.set_position(Gtk.PositionType.BOTTOM)

# On right-click, set position and popup:
def _on_result_rclick(self, gesture, n, x, y):
    pop.set_pointing_to(Gdk.Rectangle(x=int(x), y=int(y), width=1, height=1))
    pop.popup()
```

Wire actions on the window:
```python
for name, cb in [
    ("open-result",     self._ctx_open),
    ("copy-result",     self._ctx_copy),
    ("bookmark-result", self._ctx_bookmark),
]:
    action = Gio.SimpleAction(name=name)
    action.connect("activate", cb)
    self.add_action(action)
```

### Hover (statusbar link preview)

```python
motion = Gtk.EventControllerMotion()
motion.connect("motion", self._on_result_hover)
motion.connect("leave",  self._on_result_hover_leave)
self._res_view.add_controller(motion)
```

Note: `GtkColumnView` does not expose `get_path_at_pos()`. Use `pick()` to find the widget under cursor, then walk up to find the item index. Or maintain a simpler hover via selection tracking.

### Clipboard

```python
# GTK3
cb = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
cb.set_text(text, -1)
cb.store()

# GTK4
self.get_clipboard().set(text)
```

**Test:** all keyboard shortcuts work. Right-click shows menu. Statusbar shows URL on hover.

---

## Step 6 — Statusbar + settings persist

**Goal:** statusbar messages working. Settings save/load working.

### Statusbar

`GtkStatusBar` is gone. Replace with a plain `Gtk.Label`:

```python
# Build
self._statusbar = Gtk.Label(xalign=0)
self._statusbar.set_ellipsize(Pango.EllipsizeMode.END)
# in root box:
root.append(self._statusbar)

# Usage — replace push/pop pattern:
self._statusbar.set_label(message)      # show
self._statusbar.set_label(S["ready"])   # clear
```

Remove all `_statusbar.push()`, `_statusbar.pop()`, `_hover_ctx` entirely.

### Settings — window size

```python
# GTK3
w, h = self.get_size()

# GTK4
w  = self.get_width()
h  = self.get_height()
```

`resize()` → `set_default_size()` on load (GTK4 has no `resize()`).

### On close

```python
# GTK3: connect("delete-event", ...)
# GTK4:
self.connect("close-request", self._on_close)

def _on_close(self, *_):
    self._save_settings()
    return False
```

**Test:** status messages appear. Settings persist across restarts. Window size restores.

---

## Step 7 — About tab + shortcuts popover

**Goal:** About tab and `?` shortcuts popover working.

Both use `Gtk.Popover` which is unchanged in GTK4. Minor fixes:

```python
# GTK3
pop = Gtk.Popover.new(btn)
pop.add(box)
box.show_all()
pop.popup()

# GTK4
pop = Gtk.Popover()
pop.set_parent(btn)
pop.set_child(box)
pop.popup()
```

Remove `box.show_all()` — not needed.

About tab content is plain labels/links — no GTK3-specific API, copy verbatim.

**Test:** About tab renders. `?` button shows shortcuts popover.

---

## Step 8 — CSS / theming

**Goal:** Catppuccin Mocha theme applied via GTK4 CSS provider.

```python
# GTK3
provider = Gtk.CssProvider()
provider.load_from_data(CSS.encode())
Gtk.StyleContext.add_provider_for_screen(
    Gdk.Screen.get_default(), provider,
    Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
)

# GTK4
provider = Gtk.CssProvider()
provider.load_from_data(CSS.encode())
Gtk.StyleContext.add_provider_for_display(
    Gdk.Display.get_default(), provider,
    Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
)
```

Note: GTK4 CSS supports fewer properties than GTK3 in some areas (no `border-radius` on arbitrary widgets). Test and adjust the CSS file. `GtkColumnView` has its own CSS nodes (`columnview`, `columnviewcolumn`, `column-header`).

**Test:** app looks correct on Openbox, KDE, GNOME.

---

## Step 9 — Final cleanup + smoke test

- Remove all `import gi; gi.require_version("Gtk", "3.0")` leftovers
- Remove all `show_all()` calls
- Remove all `set_border_width()` calls — use margins
- Remove `_hover_ctx` statusbar context id (GTK3 artifact)
- Run on bare GTK4 install (no GTK3 fallback)
- Test on: Openbox, KDE Plasma, GNOME
- Check `python -W error::DeprecationWarning forum-scout.py` — fix any deprecation warnings

---

## Order of commits (suggested)

```
1. repo setup + backend copy (no UI yet)
2. Step 1: app skeleton
3. Step 2: top bar
4. Step 3: results tab
5. Step 4: bookmarks + history tabs
6. Step 5: event controllers
7. Step 6: statusbar + settings
8. Step 7: about + shortcuts
9. Step 8: CSS
10. Step 9: cleanup + test
```

Each commit should leave the app in a runnable state.

---

## Notes for Claude Code

- The backend section (lines 1–373 in original) is copied verbatim. Do not rewrite it.
- When porting `_build_results_tab()`, `_build_bm_tab()`, `_build_hist_tab()` — always define the `GObject.Object` subclass before the window class.
- `GObject.Object` subclasses need `from gi.repository import GObject` added to imports.
- `Gtk.ColumnView` requires the model to be a `Gtk.SelectionModel` — always wrap `Gio.ListStore` in a selection model before passing to `ColumnView`.
- Do not use `widget.add()` anywhere — it is removed in GTK4. Always use `set_child()` for single-child containers or `append()` for boxes.
- `Gtk.Box` in GTK4 has no `pack_start`/`pack_end` — use `append()` for all children. For spacing/alignment use `set_hexpand()`, `set_halign()`, or a `Gtk.Separator`.
