# Forum Scout

Multi-forum search tool for Arch-based distros. Searches Mabox, EndeavourOS, Manjaro, CachyOS, Garuda, Arch Wiki, Manjaro Wiki, CachyOS Wiki, Arch BBS, KDE, GNOME and more simultaneously.

Available on the AUR as `forum-scout`. Provides and conflicts with `forum-scout` — only one version (GTK4/Qt) can be installed at a time.

<img width="966" height="675" alt="Image" src="https://github.com/user-attachments/assets/bb46132d-d71e-440f-bc83-1c70e1fb7b53" />

<img width="966" height="675" alt="Image" src="https://github.com/user-attachments/assets/e51423b5-e25b-44f9-8c44-979254cb48a3" />

```bash
yay -S forum-scout
```

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
