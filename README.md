# Forum Scout — GTK4 port

> **Work in progress** — GTK3 → GTK4 migration of [forum-scout](https://github.com/musqz/forum-scout).

Multi-forum search tool for Arch-based distros. Searches Mabox, EndeavourOS, Manjaro, CachyOS, Garuda, Arch Wiki, Manjaro Wiki, CachyOS Wiki, Arch BBS, KDE, GNOME and more simultaneously.

## Status

The GTK4 port is functionally complete. All steps of the migration plan have been implemented and smoke-tested.

| Step | What | State |
|------|------|-------|
| 0 | Repo setup + verbatim backend copy | ✅ |
| 1 | GTK4 application skeleton | ✅ |
| 2 | Top bar (search entry, forums bar, checkboxes) | ✅ |
| 3 | Results tab (ColumnView, multi-select, sort) | ✅ |
| 4 | Bookmarks + History tabs | ✅ |
| 5 | Event controllers (keyboard shortcuts, right-click menu) | ✅ |
| 6 | Statusbar, settings persistence, suggestion dropdown | ✅ |
| 7 | About tab | ✅ |
| 8 | CSS / theming — follows system theme (no custom CSS) | ✅ |
| 9 | Cleanup + smoke test | ✅ |

## What changed from the GTK3 version

- `GtkTreeView` / `GtkListStore` → `GtkColumnView` + `Gio.ListStore` + GObject models
- `GtkStatusBar` → plain `Gtk.Label`
- `GtkEntryCompletion` (deprecated) → `Gtk.Popover` + `Gtk.ListView` suggestion dropdown
- `key-press-event` → `Gtk.EventControllerKey`
- `button-press-event` → `Gtk.GestureClick` + `Gtk.PopoverMenu`
- `Gtk.Menu` → `Gio.Menu` + `Gio.SimpleAction`
- `Gtk.Clipboard.get()` → `Gdk.Display.get_default().get_clipboard()`
- `Gtk.MessageDialog.run()` → `Gtk.AlertDialog` (async)
- `resize()` / `get_size()` → `set_default_size()` / `get_width()` / `get_height()`
- `delete-event` → `close-request`
- `widget.show_all()` / `set_border_width()` / `pack_start()` → removed / margins / `append()`

## Window decorations

The app follows the system theme and does not force client-side decorations:

- **Openbox / KDE (X11)** — the window manager draws the titlebar
- **GNOME / Wayland** — GTK4 draws its own CSD automatically

## Dependencies

- Python 3
- GTK 4
- `python-gobject`
- `python-requests`

## Run from source

```bash
python forum-scout.py
```

## Original GTK3 version

[github.com/musqz/forum-scout](https://github.com/musqz/forum-scout)
