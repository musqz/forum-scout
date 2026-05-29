# Forum Scout — GTK4 port

GTK3 → GTK4 migration of [forum-scout](https://github.com/musqz/forum-scout).

Multi-forum search tool for Arch-based distros. Searches Mabox, EndeavourOS, Manjaro, CachyOS, Garuda, Arch Wiki, Manjaro Wiki, CachyOS Wiki, Arch BBS, KDE, GNOME and more simultaneously.

## Status

The GTK4 port is **complete**. All steps of the migration plan have been implemented, tested and cleaned up on **Openbox/X11 (Mabox)**.

Testing on other desktops is welcome:
- GNOME / Wayland — CSD behaviour untested
- KDE Plasma — untested

The `packaging/PKGBUILD` is present but not yet updated for the GTK4 version — packaging is a later stage.

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

## GTK4 theme

GTK4 reads its settings from `~/.config/gtk-4.0/settings.ini` separately from GTK3. If your GTK3 dark theme also has a GTK4 variant (most do), create that file to match:

```ini
[Settings]
gtk-theme-name=YourThemeName
gtk-application-prefer-dark-theme=true
```

## Dependencies

| Package | Arch / AUR name | Tested version |
|---------|----------------|----------------|
| Python 3 | `python` | 3.14.5 |
| GTK 4 | `gtk4` | 4.22.4 |
| GLib | `glib2` | 2.88.1 |
| PyGObject | `python-gobject` | 3.56.3 |
| requests | `python-requests` | 2.34.2 |

## Run from source

```bash
python forum-scout.py
```

## Original GTK3 version

[github.com/musqz/forum-scout](https://github.com/musqz/forum-scout)
