#!/usr/bin/env python3
# ─────────────────────────────────────────────────────────────────────────────
# FORUM SCOUT — Multi-forum search tool (GTK4)
# Forum registry loaded from forums.conf (see forums.conf for format).
# ─────────────────────────────────────────────────────────────────────────────

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gtk, Gdk, GLib, Pango, Gio, GObject

import threading
import os
import json
import subprocess
import datetime
import urllib.parse
import locale
from html.parser import HTMLParser

try:
    import requests
except ImportError:
    print("Error: 'requests' not found. Install with: pip install requests")
    raise SystemExit(1)

# ─── Paths ────────────────────────────────────────────────────────────────────
CACHE_DIR     = os.path.expanduser("~/.cache/forum-scout")
BOOKMARK_FILE = os.path.join(CACHE_DIR, "bookmarks.log")
HISTORY_FILE  = os.path.join(CACHE_DIR, "history.log")
os.makedirs(CACHE_DIR, exist_ok=True)

CONFIG_DIR    = os.path.expanduser("~/.config/forum-scout")
SETTINGS_FILE = os.path.join(CONFIG_DIR, "settings.json")
os.makedirs(CONFIG_DIR, exist_ok=True)

_FORUMS_SEARCH = [
    os.path.join(CONFIG_DIR, "forums.conf"),
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "forums.conf"),
    os.path.expanduser("~/.local/share/forum-scout/forums.conf"),
    "/usr/share/forum-scout/forums.conf",
]

APP_TITLE    = "Forum Scout"
DEFAULT_HITS = 10

_VERSION = "__VERSION__"
if _VERSION.startswith("__"):
    try:
        _VERSION = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "VERSION")).read().strip()
    except Exception:
        _VERSION = "dev"

# ─── Forum registry ───────────────────────────────────────────────────────────
def _load_forums() -> list:
    for path in _FORUMS_SEARCH:
        if not os.path.exists(path):
            continue
        entries = []
        seen = set()
        with open(path) as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                try:
                    e     = json.loads(line)
                    name  = str(e.get("name",  "")).strip()
                    type_ = str(e.get("type",  "discourse")).strip()
                    url   = str(e.get("url",   "")).strip()
                    color = str(e.get("color", "#888888")).strip()
                    on    = bool(e.get("on",   True))
                    group = str(e.get("group", "distro")).strip()
                    if not name or not url or name.lower() in seen:
                        continue
                    entry = {"name": name, "type": type_, "url": url,
                             "color": color, "on": on, "group": group}
                    if "page" in e:
                        entry["page"] = str(e["page"])
                    entries.append(entry)
                    seen.add(name.lower())
                except Exception:
                    continue
        return entries
    return []

FORUMS = _load_forums()

# ─── i18n ─────────────────────────────────────────────────────────────────────
_lang = (locale.getlocale()[0] or "en")[:2]

_EN_STRINGS = {
    "search_ph":   "Type keywords and press Enter or click Search…",
    "search_btn":  "Search",
    "tab_results": "Results",
    "tab_bm":      "Bookmarks",
    "tab_hist":    "History",
    "tab_about":   "About",
    "hits_label":  "Hits per source:",
    "ready":       "Ready.",
    "fetching":    "Fetching: '{}'…",
    "done":        "{} result(s) from {} source(s).",
    "no_results":  "No results.",
    "col_n":       "#",
    "col_forum":   "Forum",
    "col_title":   "Title",
    "col_link":    "Link",
    "col_time":    "Time",
    "col_query":   "Query",
    "ctx_open":      "Open in browser",
    "ctx_copy":      "Copy link",
    "ctx_bm":        "Add to bookmarks",
    "ctx_bm_remove": "Remove bookmark",
    "bm_open":     "Open",
    "bm_copy":     "Copy link",
    "bm_del":      "Remove",
    "bm_added":    "Bookmark added: {}",
    "bm_removed":  "Bookmark removed.",
    "hist_rerun":  "Re-run search",
    "hist_clear":  "Clear history",
    "via_ddg":     " ⁽ᴰᴰᴳ⁾",
    "col_date":    "Added",
}

def _load_translation(lang: str) -> dict:
    """Load translation from external JSON file; fall back to English."""
    search_dirs = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "translations"),
        os.path.expanduser("~/.local/share/forum-scout/translations"),
        "/usr/share/forum-scout/translations",
    ]
    for lang_code in (lang, "en"):
        for d in search_dirs:
            path = os.path.join(d, f"{lang_code}.json")
            if os.path.exists(path):
                try:
                    with open(path, encoding="utf-8") as f:
                        data = json.load(f)
                        return {**_EN_STRINGS, **data}
                except Exception:
                    pass
    return _EN_STRINGS

S = _load_translation(_lang)

# ─── HTTP session ─────────────────────────────────────────────────────────────
_session = requests.Session()
_session.headers["User-Agent"] = (
    f"forum-scout/{_VERSION} (https://github.com/musqz/forum-scout)"
)

# ─── DuckDuckGo HTML parser ───────────────────────────────────────────────────
class _DDGParser(HTMLParser):
    """Minimal parser that extracts result links from DDG HTML response."""

    def __init__(self):
        super().__init__()
        self.results: list[tuple[str, str]] = []
        self._link: str | None = None
        self._title_buf: list[str] = []
        self._in_a: bool = False

    def handle_starttag(self, tag, attrs):
        if tag != "a":
            return
        d = dict(attrs)
        cls = d.get("class", "")
        if "result__a" not in cls:
            return
        href = d.get("href", "")
        # DDG wraps real URLs in a redirect — unwrap if present
        if "uddg=" in href:
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
            href = urllib.parse.unquote(qs.get("uddg", [""])[0])
        self._link = href
        self._title_buf = []
        self._in_a = True

    def handle_endtag(self, tag):
        if tag == "a" and self._in_a:
            self._in_a = False
            title = "".join(self._title_buf).strip()
            if self._link and title:
                self.results.append((title, self._link))
            self._link = None
            self._title_buf = []

    def handle_data(self, data):
        if self._in_a:
            self._title_buf.append(data)


# ─── Fetcher functions ────────────────────────────────────────────────────────
def _fmt_date(iso: str) -> str:
    """Parse an ISO-8601 timestamp and return YYYY-MM-DD, or '' on failure."""
    try:
        # Replace trailing Z for Python < 3.11 compat
        return datetime.datetime.fromisoformat(
            iso.replace("Z", "+00:00")
        ).strftime("%Y-%m-%d")
    except Exception:
        return ""


class _ForumUnreachable(Exception):
    pass


_NET_ERRORS = (requests.ConnectionError, requests.Timeout, requests.exceptions.SSLError)


def _fetch_discourse(forum: dict, query: str, hits: int) -> list[tuple[str, str, str]]:
    url = f"{forum['url']}/search.json"
    try:
        r = _session.get(url, params={"q": query}, timeout=9)
        data = r.json()
        out = []
        base = forum["url"]
        for t in data.get("topics", [])[:hits]:
            link = f"{base}/t/{t['slug']}/{t['id']}"
            date = _fmt_date(t.get("created_at", ""))
            out.append((t["title"], link, date))
        return out
    except _NET_ERRORS:
        raise _ForumUnreachable
    except Exception:
        return []


def _fetch_mediawiki(forum: dict, query: str, hits: int) -> list[tuple[str, str, str]]:
    try:
        r = _session.get(
            f"{forum['url']}/api.php",
            params={
                "action": "query",
                "list": "search",
                "srsearch": query,
                "srlimit": hits,
                "format": "json",
            },
            timeout=9,
        )
        data = r.json()
        out = []
        base = forum["url"]
        page_tpl = forum.get("page", "title/{slug}")
        for item in data.get("query", {}).get("search", []):
            slug = urllib.parse.quote(item["title"].replace(" ", "_"))
            date = _fmt_date(item.get("timestamp", ""))
            out.append((item["title"], f"{base}/{page_tpl.format(slug=slug)}", date))
        return out
    except _NET_ERRORS:
        raise _ForumUnreachable
    except Exception:
        return []


def _fetch_ddg(forum: dict, query: str, hits: int) -> list[tuple[str, str, str]]:
    site = forum["url"]
    try:
        r = requests.get(
            "https://html.duckduckgo.com/html/",
            params={"q": f"site:{site} {query}"},
            headers={"User-Agent": _session.headers["User-Agent"]},
            timeout=12,
        )
        parser = _DDGParser()
        parser.feed(r.text)
        out = []
        for title, link in parser.results:
            if site in link:
                out.append((title, link, "—"))   # DDG returns no date
                if len(out) >= hits:
                    break
        return out
    except _NET_ERRORS:
        raise _ForumUnreachable
    except Exception:
        return []


_FETCHERS = {
    "discourse":  _fetch_discourse,
    "mediawiki":  _fetch_mediawiki,
    "ddg":        _fetch_ddg,
}

# ─── Live suggestion fetchers ─────────────────────────────────────────────────
_SUGGEST_LIMIT   = 5     # results per forum for suggestions
_SUGGEST_TIMEOUT = 4     # seconds — must be fast or feel broken
_SUGGEST_DELAY   = 400   # ms debounce — wait this long after last keystroke


def _suggest_discourse(forum: dict, term: str) -> list[str]:
    try:
        r = _session.get(
            f"{forum['url']}/search.json",
            params={"q": term},
            timeout=_SUGGEST_TIMEOUT,
        )
        data = r.json()
        return [t["title"] for t in data.get("topics", [])[:_SUGGEST_LIMIT]]
    except Exception:
        return []


def _suggest_mediawiki(forum: dict, term: str) -> list[str]:
    """Uses MediaWiki opensearch — the purpose-built typeahead endpoint."""
    try:
        r = _session.get(
            f"{forum['url']}/api.php",
            params={
                "action":    "opensearch",
                "search":    term,
                "limit":     _SUGGEST_LIMIT,
                "namespace": 0,
                "format":    "json",
            },
            timeout=_SUGGEST_TIMEOUT,
        )
        data = r.json()
        return list(data[1])[:_SUGGEST_LIMIT] if len(data) > 1 else []
    except Exception:
        return []


_SUGGESTERS = {
    "discourse": _suggest_discourse,
    "mediawiki": _suggest_mediawiki,
    # "ddg" intentionally omitted — too slow for typeahead
}

# Forum name → color, used for consistent coloring across all tabs
_FORUM_COLOR: dict[str, str] = {f["name"]: f["color"] for f in FORUMS}

# ─── Autocomplete seed terms ──────────────────────────────────────────────────
# Common Linux forum search topics shown to new users before history builds up
_SEED_TERMS = [
    # Boot & system
    "black screen after update", "black screen on boot", "boot loop",
    "grub not found", "uefi boot", "initramfs error", "kernel panic",
    "slow boot", "systemd timeout", "failed to start",
    # Hardware
    "nvidia driver", "amd gpu", "intel graphics", "screen tearing",
    "wifi not working", "bluetooth not working", "no sound", "audio crackling",
    "touchpad not working", "webcam not detected", "dual monitor setup",
    "monitor not detected", "hdmi no signal",
    # Package management
    "pacman error", "yay aur", "package conflict", "dependency error",
    "signature invalid", "keyring update", "partial upgrade",
    # Desktop & compositor
    "picom animations", "picom vsync", "openbox keybind", "tint2 config",
    "conky not showing", "jgmenu setup", "wayland issues", "xorg crash",
    # KDE
    "plasma crash", "plasma black screen", "kwin compositor",
    "kde panel not showing", "plasma widget", "kde slow",
    "dolphin not opening", "kde login loop", "sddm not starting",
    "kde wayland issues", "krunner not working", "kde notifications",
    # GNOME
    "gnome shell crash", "gnome extensions not working", "gdm not starting",
    "gnome panel missing", "nautilus not opening", "gnome slow",
    "gnome wayland black screen", "gnome login loop", "gnome freezes",
    "gnome screen flickering", "gnome night light", "dash to dock",
    # Network
    "networkmanager wifi", "ethernet not working", "vpn setup", "dns slow",
    # Suspend & power
    "suspend not working", "hibernate resume", "wake from sleep",
    "screen blank after suspend", "battery drain",
    # Apps
    "firefox slow", "steam not launching", "flatpak permission",
    "wine not working", "virtualbox error",
]


# ─── CSS ──────────────────────────────────────────────────────────────────────
# ─── Data models ──────────────────────────────────────────────────────────────
class ResultItem(GObject.Object):
    __gtype_name__ = "ResultItem"

    def __init__(self, marker, forum, color, title, link, date):
        super().__init__()
        self.marker = marker   # "★" when the URL is bookmarked, else ""
        self.forum  = forum    # display name (may carry the via-DDG suffix)
        self.color  = color
        self.title  = title
        self.link   = link
        self.date   = date


class BookmarkItem(GObject.Object):
    __gtype_name__ = "BookmarkItem"

    def __init__(self, forum, title, link, date, color):
        super().__init__()
        self.forum = forum
        self.title = title
        self.link  = link
        self.date  = date
        self.color = color


class HistoryItem(GObject.Object):
    __gtype_name__ = "HistoryItem"

    def __init__(self, time, query):
        super().__init__()
        self.time  = time
        self.query = query


# ─── Main window ──────────────────────────────────────────────────────────────
class ScoutWindow(Gtk.ApplicationWindow):

    def __init__(self, app):
        super().__init__(application=app, title=APP_TITLE)
        self.set_icon_name("system-search")
        self.set_default_size(820, 520)
        self.set_size_request(700, 300)

        self._busy               = False
        self._results            = []
        self._bm_data            = []
        self._suggest_timer      = None
        self._suggest_token      = 0
        self._live_count         = 0
        self._forums_bar_visible = True
        self._bm_bulk_confirm    = True
        self._bm_undo_data       = []

        self._build_ui()
        self.present()

    # ── UI ────────────────────────────────────────────────────────────────────
    def _build_ui(self):
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.set_child(root)

        root.append(self._build_topbar())

        notebook = self._build_notebook()
        notebook.set_vexpand(True)
        root.append(notebook)
        # statusbar (Step 6) appended in a later step

        # apply initial forums-bar visibility (settings load in Step 6)
        self._forums_bar.set_visible(self._forums_bar_visible)
        self._forums_toggle.set_label(
            "Forums ▾" if self._forums_bar_visible else "Forums ▸"
        )

    # ── Top bar ───────────────────────────────────────────────────────────────
    def _build_topbar(self):
        bar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        bar.set_margin_start(6)
        bar.set_margin_end(6)
        bar.set_margin_top(6)

        # Row 1 — search entry + button + spinner
        row1 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        bar.append(row1)

        self._entry = Gtk.Entry()
        self._entry.set_placeholder_text(S["search_ph"])
        self._entry.set_hexpand(True)
        self._entry.connect("activate", self._on_search)
        self._entry.connect("changed",  self._on_entry_changed)
        # live suggestions / completion wired in Step 5 (_build_completion)
        row1.append(self._entry)

        self._btn = Gtk.Button(label=S["search_btn"])
        self._btn.connect("clicked", self._on_search)
        row1.append(self._btn)

        self._spinner = Gtk.Spinner()
        row1.append(self._spinner)

        self._forums_toggle = Gtk.Button(label="Forums ▾")
        self._forums_toggle.set_tooltip_text("Show/hide forums bar (Ctrl+F)")
        self._forums_toggle.connect("clicked", self._toggle_forums_bar)
        row1.append(self._forums_toggle)

        help_btn = Gtk.Button(label="?")
        help_btn.set_tooltip_text("Keyboard shortcuts")
        help_btn.connect("clicked", self._show_shortcuts)
        row1.append(help_btn)
        self._help_btn = help_btn

        # Forums bar — rows 2–4, toggled as a unit
        self._forums_bar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        bar.append(self._forums_bar)

        # Row 2 — distro forums (FlowBox wraps to next line if too many)
        row2 = Gtk.FlowBox()
        row2.set_selection_mode(Gtk.SelectionMode.NONE)
        row2.set_row_spacing(4)
        row2.set_column_spacing(8)
        row2.set_max_children_per_line(50)
        self._forums_bar.append(row2)

        # Row 3 — wikis
        row3 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._forums_bar.append(row3)

        # Row 4 — DE/WM forums + hits spinner
        row4 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._forums_bar.append(row4)

        self._checks: dict[str, Gtk.CheckButton] = {}
        for f in FORUMS:
            cb = Gtk.CheckButton()
            cb.set_active(f["on"])
            lbl = Gtk.Label()
            lbl.set_markup(f'<span foreground="{f["color"]}" weight="bold">{f["name"]}</span>')
            cb.set_child(lbl)
            self._checks[f["name"]] = cb
            if f["group"] == "distro":
                row2.append(cb)
            elif f["group"] == "wiki":
                row3.append(cb)
            else:  # de
                row4.append(cb)

        spacer = Gtk.Label()
        spacer.set_hexpand(True)
        row4.append(spacer)

        hits_label = Gtk.Label(label=S["hits_label"])
        hits_label.add_css_class("dim-label")
        row4.append(hits_label)

        adj = Gtk.Adjustment(value=DEFAULT_HITS, lower=1, upper=50, step_increment=1, page_increment=5)
        self._hits_spin = Gtk.SpinButton(adjustment=adj, climb_rate=1, digits=0)
        row4.append(self._hits_spin)

        return bar

    def _toggle_forums_bar(self, *_):
        self._forums_bar_visible = not self._forums_bar_visible
        self._forums_bar.set_visible(self._forums_bar_visible)
        self._forums_toggle.set_label("Forums ▾" if self._forums_bar_visible else "Forums ▸")

    def _show_shortcuts(self, btn):
        pop = Gtk.Popover()
        pop.set_parent(btn)
        pop.connect("closed", lambda p: p.unparent())
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_margin_start(12)
        box.set_margin_end(12)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        grid = Gtk.Grid(column_spacing=20, row_spacing=4)
        grid.set_halign(Gtk.Align.CENTER)
        for row, (key, desc) in enumerate((
            ("Ctrl+L",      "Focus search bar"),
            ("F6",          "Focus table (tab-aware)"),
            ("Ctrl+F",      "Toggle forums bar"),
            ("F5",          "Re-run last search"),
            ("Escape",      "Clear search"),
            ("Enter",        "Open selected (all if multi-select)"),
            ("Ctrl+Enter",  "Open selected result(s) in browser"),
            ("Ctrl+B",      "Bookmark / un-bookmark selected result(s)"),
            ("Del",         "Delete selected bookmark(s)"),
            ("Ctrl+Z",      "Undo last bookmark delete"),
            ("Ctrl+Tab",    "Switch tabs"),
            ("?",           "Show this help"),
        )):
            k = Gtk.Label()
            k.set_markup(f"<b>{key}</b>")
            k.set_halign(Gtk.Align.END)
            grid.attach(k,                    0, row, 1, 1)
            grid.attach(Gtk.Label(label=desc), 1, row, 1, 1)
        box.append(grid)
        pop.set_child(box)
        pop.popup()

    # ── Notebook ──────────────────────────────────────────────────────────────
    def _build_notebook(self):
        self._notebook = Gtk.Notebook()

        self._res_tab_label = Gtk.Label(label=S["tab_results"])
        self._notebook.append_page(self._build_results_tab(), self._res_tab_label)
        self._notebook.append_page(self._build_bm_tab(),   Gtk.Label(label=S["tab_bm"]))
        self._notebook.append_page(self._build_hist_tab(), Gtk.Label(label=S["tab_hist"]))
        # about tab: Step 7

        return self._notebook

    # ── ColumnView helpers ──────────────────────────────────────────────────────
    @staticmethod
    def _make_label_factory(attr, colored=False, bold=False):
        """Label-per-cell factory; reads `attr` off the row item, optionally
        coloring it with the item's `color` and/or bolding it."""
        factory = Gtk.SignalListItemFactory()

        def on_setup(_f, list_item):
            lbl = Gtk.Label(xalign=0)
            lbl.set_ellipsize(Pango.EllipsizeMode.END)
            list_item.set_child(lbl)

        def on_bind(_f, list_item):
            obj  = list_item.get_item()
            lbl  = list_item.get_child()
            esc  = GLib.markup_escape_text(getattr(obj, attr))
            if colored and bold:
                lbl.set_markup(f'<span foreground="{obj.color}" weight="600">{esc}</span>')
            elif colored:
                lbl.set_markup(f'<span foreground="{obj.color}">{esc}</span>')
            elif bold:
                lbl.set_markup(f'<span weight="600">{esc}</span>')
            else:
                lbl.set_label(getattr(obj, attr))

        factory.connect("setup", on_setup)
        factory.connect("bind",  on_bind)
        return factory

    # ── Results tab ───────────────────────────────────────────────────────────
    def _build_results_tab(self):
        sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        sw.set_vexpand(True)

        self._res_store = Gio.ListStore(item_type=ResultItem)

        cv = Gtk.ColumnView()
        cv.connect("activate", self._on_result_activate)
        self._res_view = cv

        _factory = self._make_label_factory

        def _column(title, factory, fixed_w=None, expand=False, sorter=None):
            col = Gtk.ColumnViewColumn(title=title, factory=factory)
            if expand:
                col.set_expand(True)
            if fixed_w:
                col.set_fixed_width(fixed_w)
            if sorter:
                col.set_sorter(sorter)
            cv.append_column(col)
            return col

        forum_sorter = Gtk.CustomSorter.new(self._cmp_forum)
        date_sorter  = Gtk.CustomSorter.new(self._cmp_date)

        self._col_res_n     = _column(S["col_n"],     _factory("marker"),              fixed_w=28)
        self._col_res_forum = _column(S["col_forum"], _factory("forum", colored=True), fixed_w=150,
                                      sorter=forum_sorter)
        _column(S["col_title"], _factory("title", bold=True), expand=True)
        self._col_res_date  = _column(S["col_date"],  _factory("date"),                fixed_w=100,
                                      sorter=date_sorter)

        # Sorting only applies when the data flows through a SortListModel driven
        # by the ColumnView's own (header-click) sorter.
        sort_model = Gtk.SortListModel(model=self._res_store, sorter=cv.get_sorter())
        self._res_selection = Gtk.MultiSelection(model=sort_model)
        cv.set_model(self._res_selection)
        cv.sort_by_column(self._col_res_date, Gtk.SortType.DESCENDING)  # default: newest first

        sw.set_child(cv)
        return sw

    # ── Bookmarks tab ─────────────────────────────────────────────────────────
    def _build_bm_tab(self):
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        vbox.set_margin_start(6)
        vbox.set_margin_end(6)
        vbox.set_margin_top(6)
        vbox.set_margin_bottom(6)

        # Filter entry
        self._bm_filter_entry = Gtk.SearchEntry()
        self._bm_filter_entry.set_placeholder_text("Filter bookmarks…")
        self._bm_filter_entry.connect("changed", self._on_bm_filter_changed)
        vbox.append(self._bm_filter_entry)

        tb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        vbox.append(tb)
        for label, cb in [
            (S["bm_open"], self._bm_open),
            (S["bm_copy"], self._bm_copy),
            (S["bm_del"],  self._bm_remove),
        ]:
            btn = Gtk.Button(label=label)
            btn.connect("clicked", cb)
            tb.append(btn)

        sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        sw.set_vexpand(True)

        # Master store mirrors self._bm_data; FilterListModel applies the text
        # filter, SortListModel applies header-click sorting.
        self._bm_store = Gio.ListStore(item_type=BookmarkItem)
        self._bm_filter = Gtk.CustomFilter.new(self._bm_filter_fn)
        filtered = Gtk.FilterListModel(model=self._bm_store, filter=self._bm_filter)

        cv = Gtk.ColumnView()
        cv.connect("activate", self._on_bm_activate)
        self._bm_view = cv

        forum_sorter = Gtk.CustomSorter.new(self._cmp_bm_forum)
        date_sorter  = Gtk.CustomSorter.new(self._cmp_bm_date)

        self._col_bm_forum = Gtk.ColumnViewColumn(
            title=S["col_forum"],
            factory=self._make_label_factory("forum", colored=True, bold=True))
        self._col_bm_forum.set_fixed_width(130)
        self._col_bm_forum.set_sorter(forum_sorter)
        cv.append_column(self._col_bm_forum)

        title_col = Gtk.ColumnViewColumn(
            title=S["col_title"],
            factory=self._make_label_factory("title", bold=True))
        title_col.set_expand(True)
        cv.append_column(title_col)

        self._col_bm_date = Gtk.ColumnViewColumn(
            title=S["col_date"],
            factory=self._make_label_factory("date"))
        self._col_bm_date.set_fixed_width(145)
        self._col_bm_date.set_sorter(date_sorter)
        cv.append_column(self._col_bm_date)

        sort_model = Gtk.SortListModel(model=filtered, sorter=cv.get_sorter())
        self._bm_selection = Gtk.MultiSelection(model=sort_model)
        cv.set_model(self._bm_selection)
        cv.sort_by_column(self._col_bm_date, Gtk.SortType.DESCENDING)
        # key shortcuts (Delete / Return) wired in Step 5

        sw.set_child(cv)
        vbox.append(sw)
        self._load_bookmarks()
        return vbox

    # ── History tab ───────────────────────────────────────────────────────────
    def _build_hist_tab(self):
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        vbox.set_margin_start(6)
        vbox.set_margin_end(6)
        vbox.set_margin_top(6)
        vbox.set_margin_bottom(6)

        tb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        vbox.append(tb)
        for label, cb in [
            (S["hist_rerun"],  self._hist_rerun),
            (S["hist_clear"],  self._hist_clear),
        ]:
            btn = Gtk.Button(label=label)
            btn.connect("clicked", cb)
            tb.append(btn)

        sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        sw.set_vexpand(True)

        self._hist_store = Gio.ListStore(item_type=HistoryItem)
        self._hist_selection = Gtk.SingleSelection(model=self._hist_store)
        self._hist_selection.set_autoselect(False)
        self._hist_selection.set_can_unselect(True)

        cv = Gtk.ColumnView(model=self._hist_selection)
        cv.connect("activate", self._on_hist_activate)
        self._hist_view = cv

        self._col_hist_time = Gtk.ColumnViewColumn(
            title=S["col_time"], factory=self._make_label_factory("time"))
        self._col_hist_time.set_fixed_width(160)
        cv.append_column(self._col_hist_time)

        query_col = Gtk.ColumnViewColumn(
            title=S["col_query"], factory=self._make_label_factory("query"))
        query_col.set_expand(True)
        cv.append_column(query_col)

        sw.set_child(cv)
        vbox.append(sw)
        self._load_history()
        return vbox

    # ── About tab ─────────────────────────────────────────────────────────────
    def _build_about_tab(self):
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        inner.set_border_width(16)
        inner.set_valign(Gtk.Align.CENTER)
        inner.set_halign(Gtk.Align.CENTER)
        outer.set_valign(Gtk.Align.CENTER)

        def _lbl(markup=None, text=None, size=None):
            l = Gtk.Label()
            l.set_selectable(True)
            if markup:
                l.set_markup(markup)
            else:
                l.set_label(text)
            if size:
                attrs = Pango.AttrList()
                attrs.insert(Pango.attr_scale_new(size))
                l.set_attributes(attrs)
            return l

        inner.pack_start(_lbl(markup=f"<b>Forum Scout</b>", size=1.8),    False, False, 0)
        inner.pack_start(_lbl(text=f"v{_VERSION}"),                        False, False, 0)
        inner.pack_start(Gtk.Separator(),                                  False, False, 4)
        inner.pack_start(_lbl(markup='<a href="https://github.com/musqz/forum-scout">github.com/musqz/forum-scout</a>'), False, False, 0)
        inner.pack_start(_lbl(markup="musqz · MIT"),                       False, False, 0)

        outer.pack_start(inner, True, True, 0)
        return outer

    # ── Status bar ────────────────────────────────────────────────────────────
    def _build_statusbar(self):
        self._statusbar = Gtk.Statusbar()
        self._statusbar.get_style_context().add_class("statusbar")
        self._ctx       = self._statusbar.get_context_id("main")
        self._hover_ctx = self._statusbar.get_context_id("hover")
        self._hover_link = None
        self._set_status(S["ready"])

        self._suggest_lbl = Gtk.Label(label="loading suggestions…")
        self._suggest_lbl.set_margin_end(8)
        self._suggest_lbl.set_no_show_all(True)

        self._undo_btn = Gtk.Button(label="Undo")
        self._undo_btn.set_tooltip_text("Restore last deleted bookmark(s) (Ctrl+Z)")
        self._undo_btn.connect("clicked", self._bm_undo)
        self._undo_btn.set_no_show_all(True)

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        box.pack_start(self._statusbar,   True,  True,  0)
        box.pack_end(self._suggest_lbl,   False, False, 0)
        box.pack_end(self._undo_btn,      False, False, 0)
        return box

    def _set_status(self, msg: str):
        if not hasattr(self, "_statusbar"):
            return  # statusbar built in Step 6
        self._statusbar.pop(self._ctx)
        self._statusbar.push(self._ctx, msg)

    # ── Search logic ─────────────────────────────────────────────────────────
    def _on_search(self, *_):
        query = self._entry.get_text().strip()
        if not query or self._busy:
            return
        if not hasattr(self, "_res_store"):
            return  # results tab not built yet (Step 3)

        active = [f for f in FORUMS if self._checks[f["name"]].get_active()]
        if not active:
            self._set_status(S["no_results"])
            return

        if hasattr(self, "_undo_btn"):
            self._undo_btn.set_visible(False)   # statusbar built in Step 6
        self._bm_undo_data = []
        self._busy = True
        self._btn.set_sensitive(False)
        self._spinner.start()
        self._res_store.remove_all()
        self._results       = []
        self._search_total  = len(active)
        self._search_done   = 0
        self._search_idx    = 0
        self._ddg_empty     = []
        self._unreachable   = []
        self._search_query  = query
        self._tab_switched  = False
        # snapshot of bookmarked URLs so _add_forum_results can mark them
        self._bm_urls = self._bookmarked_urls()
        self._set_status(S["fetching"].format(query))
        self._log_history(query)

        hits = int(self._hits_spin.get_value())
        for f in active:
            threading.Thread(
                target=self._fetch_one_forum,
                args=(query, hits, f),
                daemon=True,
            ).start()

    def _fetch_one_forum(self, query: str, hits: int, forum: dict):
        try:
            items = _FETCHERS[forum["type"]](forum, query, hits)
            unreachable = None
        except _ForumUnreachable:
            items = []
            unreachable = forum["name"]
        via_ddg = forum["type"] == "ddg"
        results = [
            (forum["name"], forum["color"], title, link, date, via_ddg)
            for title, link, date in items
        ]
        ddg_empty = forum["name"] if via_ddg and not items and not unreachable else None
        GLib.idle_add(self._add_forum_results, results, ddg_empty, unreachable)

    def _add_forum_results(self, new_results: list, ddg_empty_name, unreachable_name):
        for forum, color, title, link, date, via_ddg in new_results:
            self._search_idx += 1
            display = forum + (S["via_ddg"] if via_ddg else "")
            marker  = "★" if link in self._bm_urls else ""
            self._res_store.append(ResultItem(marker, display, color, title, link, date))
            self._results.append((self._search_idx, forum, color, title, link, date, via_ddg))

        if ddg_empty_name:
            self._ddg_empty.append(ddg_empty_name)
        if unreachable_name:
            self._unreachable.append(unreachable_name)

        self._search_done += 1
        total = len(self._results)
        self._res_tab_label.set_text(f"{S['tab_results']} ({total})")

        if self._search_done < self._search_total:
            self._set_status(
                f"{S['fetching'].format(self._search_query)}"
                f"  ({self._search_done}/{self._search_total})"
            )
        else:
            sources = len({r[1] for r in self._results})
            status  = S["done"].format(total, sources)
            if self._ddg_empty:
                status += "  ·  " + ", ".join(self._ddg_empty) + ": no results (DDG — try again)"
            if self._unreachable:
                status += "  ·  ⚠ " + ", ".join(self._unreachable) + ": unreachable"
            self._set_status(status)
            self._spinner.stop()
            self._btn.set_sensitive(True)
            self._busy = False

        if new_results and not self._tab_switched:
            self._notebook.set_current_page(0)
            self._tab_switched = True

    # ── Sort helpers ──────────────────────────────────────────────────────────
    @staticmethod
    def _cmp_forum(a, b, _data):
        return (a.forum > b.forum) - (a.forum < b.forum)

    @staticmethod
    def _cmp_date(a, b, _data):
        da = "0000-00-00" if a.date in ("—", "") else a.date
        db = "0000-00-00" if b.date in ("—", "") else b.date
        return (da > db) - (da < db)

    @staticmethod
    def _cmp_bm_forum(a, b, _data):
        return (a.forum > b.forum) - (a.forum < b.forum)

    @staticmethod
    def _cmp_bm_date(a, b, _data):
        return (a.date > b.date) - (a.date < b.date)

    # ── Result interactions ───────────────────────────────────────────────────
    def _on_result_activate(self, _cv, position):
        item = self._res_selection.get_item(position)
        if item is not None:
            self._open_url(item.link)

    def _on_result_rclick(self, view, event):
        if event.button != 3:
            return False
        info = view.get_path_at_pos(int(event.x), int(event.y))
        if not info:
            return False
        path = info[0]
        sel  = view.get_selection()
        if not sel.path_is_selected(path):
            sel.unselect_all()
            sel.select_path(path)
        self._show_result_menu(event=event)
        return True

    def _on_result_popup_menu(self, view):
        path, _ = view.get_cursor()
        if path is None:
            return False
        sel = view.get_selection()
        if not sel.path_is_selected(path):
            sel.unselect_all()
            sel.select_path(path)
        self._show_result_menu(event=None)
        return True

    def _show_result_menu(self, event):
        sel = self._res_view.get_selection()
        model, paths = sel.get_selected_rows()
        if not paths:
            return
        n = len(paths)
        menu = Gtk.Menu()

        if n == 1:
            it    = model.get_iter(paths[0])
            forum = model.get_value(it, 1)
            title = model.get_value(it, 3)
            link  = model.get_value(it, 4)
            already_bm = link in {r[2] for r in self._bm_data}
            actions = [
                (S["ctx_open"], lambda *_: self._open_url(link)),
                (S["ctx_copy"], lambda *_: self._copy(link)),
            ]
            if already_bm:
                actions.append((S["ctx_bm_remove"], lambda *_: self._bm_remove_by_link(link)))
            else:
                actions.append((S["ctx_bm"], lambda *_: self._add_bookmark(forum, title, link)))
        else:
            bm_urls   = self._bookmarked_urls()
            links     = [model.get_value(model.get_iter(p), 4) for p in paths]
            to_add    = [p for p, l in zip(paths, links) if l not in bm_urls]
            to_remove = [p for p, l in zip(paths, links) if l in bm_urls]
            actions = [(f"Open {n} in browser", lambda *_: self._open_results_multi(paths))]
            if to_add:
                actions.append((f"Add {len(to_add)} to bookmarks",
                                 lambda *_, r=to_add: self._bookmark_results_multi(r)))
            if to_remove:
                actions.append((f"Remove {len(to_remove)} bookmark(s)",
                                 lambda *_, r=to_remove: self._unbookmark_results_multi(r)))

        for label, cb in actions:
            item = Gtk.MenuItem(label=label)
            item.connect("activate", cb)
            menu.append(item)
        menu.show_all()
        if event:
            menu.popup_at_pointer(event)
        else:
            path, col = self._res_view.get_cursor()
            rect = self._res_view.get_cell_area(path, col)
            menu.popup_at_rect(
                self._res_view.get_window(), rect,
                Gdk.Gravity.SOUTH_WEST, Gdk.Gravity.NORTH_WEST, None
            )

    def _open_results_multi(self, paths):
        links = [self._res_store.get_value(self._res_store.get_iter(p), 4) for p in paths]
        links = [l for l in links if l]
        if not links:
            return
        if len(links) > 15:
            dlg = Gtk.MessageDialog(
                transient_for=self, flags=0,
                message_type=Gtk.MessageType.QUESTION,
                buttons=Gtk.ButtonsType.OK_CANCEL,
                text=f"Open {len(links)} tabs in your browser?",
            )
            dlg.set_default_response(Gtk.ResponseType.CANCEL)
            response = dlg.run()
            dlg.destroy()
            if response != Gtk.ResponseType.OK:
                return
        for url in links:
            self._open_url(url)

    def _bookmark_results_multi(self, paths):
        bm_urls = self._bookmarked_urls()
        added = 0
        for p in paths:
            it    = self._res_store.get_iter(p)
            link  = self._res_store.get_value(it, 4)
            if not link or link in bm_urls:
                continue
            forum = self._res_store.get_value(it, 1)
            title = self._res_store.get_value(it, 3)
            self._add_bookmark(forum, title, link)
            bm_urls.add(link)
            added += 1
        if added:
            self._set_status(f"{added} bookmark(s) added.")

    def _unbookmark_results_multi(self, paths):
        links = {self._res_store.get_value(self._res_store.get_iter(p), 4) for p in paths}
        links.discard("")
        to_remove = self._bookmarked_urls() & links
        if not to_remove:
            return
        self._bm_data = [bm for bm in self._bm_data if bm[2] not in to_remove]
        self._bm_refresh()
        for link in to_remove:
            self._mark_result_unbookmarked(link)
        with open(BOOKMARK_FILE, "w") as fh:
            for f, t, l, d, _ in self._bm_data:
                fh.write(f"[{f}] {t} - {l}|||{d}\n")
        self._set_status(f"{len(to_remove)} bookmark(s) removed.")

    # ── Bookmarks ─────────────────────────────────────────────────────────────
    def _add_bookmark(self, forum: str, title: str, link: str):
        date  = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        color = _FORUM_COLOR.get(forum, "#cdd6f4")
        with open(BOOKMARK_FILE, "a") as f:
            f.write(f"[{forum}] {title} - {link}|||{date}\n")
        self._bm_data.append([forum, title, link, date, color])
        self._bm_refresh()
        self._mark_result_bookmarked(link)
        self._set_status(S["bm_added"].format(title))

    def _mark_result_bookmarked(self, link: str):
        self._set_result_marker(link, "★")

    def _mark_result_unbookmarked(self, link: str):
        self._set_result_marker(link, "")

    def _set_result_marker(self, link: str, marker: str):
        for i in range(self._res_store.get_n_items()):
            item = self._res_store.get_item(i)
            if item.link == link and item.marker != marker:
                item.marker = marker
                self._res_store.items_changed(i, 1, 1)  # force the cell to rebind

    def _bookmarked_urls(self) -> set:
        return {row[2] for row in self._bm_data}

    def _bm_refresh(self):
        # rebuild the master store from _bm_data; the text filter is applied by
        # the FilterListModel layer, not here
        self._bm_store.remove_all()
        for forum, title, link, date, color in self._bm_data:
            self._bm_store.append(BookmarkItem(forum, title, link, date, color))

    def _bm_filter_fn(self, item, _user_data=None):
        text = self._bm_filter_entry.get_text().strip().lower()
        if not text:
            return True
        return (text in item.forum.lower()
                or text in item.title.lower()
                or text in item.link.lower())

    def _on_bm_filter_changed(self, _entry):
        self._bm_filter.changed(Gtk.FilterChange.DIFFERENT)

    def _load_bookmarks(self):
        self._bm_data = []
        if not os.path.exists(BOOKMARK_FILE):
            self._bm_refresh()
            return
        with open(BOOKMARK_FILE) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    forum = line.split("]")[0].lstrip("[")
                    rest  = line.split("] ", 1)[1]
                    if "|||" in rest:
                        body, date = rest.rsplit("|||", 1)
                    else:
                        body, date = rest, ""
                    cut = body.rfind(" - http")
                    if cut == -1:
                        cut = body.rfind(" - ")
                    title = body[:cut]
                    link  = body[cut + 3:]
                    color = _FORUM_COLOR.get(forum, "#cdd6f4")
                    self._bm_data.append([forum, title, link, date, color])
                except Exception:
                    pass
        self._bm_refresh()

    def _write_bookmarks(self):
        with open(BOOKMARK_FILE, "w") as fh:
            for f, t, l, d, _ in self._bm_data:
                fh.write(f"[{f}] {t} - {l}|||{d}\n")

    @staticmethod
    def _selected_items(selection):
        bitset = selection.get_selection()
        return [selection.get_item(bitset.get_nth(i)) for i in range(bitset.get_size())]

    def _confirm(self, message, ok_label, on_ok):
        """Async yes/no confirmation (GTK4 has no blocking dialog.run())."""
        dlg = Gtk.AlertDialog()
        dlg.set_modal(True)
        dlg.set_message(message)
        dlg.set_buttons(["Cancel", ok_label])
        dlg.set_cancel_button(0)
        dlg.set_default_button(1)

        def on_choice(d, res):
            try:
                if d.choose_finish(res) == 1:
                    on_ok()
            except GLib.Error:
                pass   # dismissed

        dlg.choose(self, None, on_choice)

    def _bm_open(self, *_):
        links = [it.link for it in self._selected_items(self._bm_selection) if it.link]
        if not links:
            return
        if len(links) > 15:
            self._confirm(f"Open {len(links)} tabs in your browser?", "Open",
                          lambda: [self._open_url(u) for u in links])
            return
        for url in links:
            self._open_url(url)

    def _bm_copy(self, *_):
        links = [it.link for it in self._selected_items(self._bm_selection) if it.link]
        if links:
            self._copy("\n".join(links))

    def _bm_remove(self, *_):
        links = self._bm_selected_links()
        if not links:
            return
        if len(links) > 5 and self._bm_bulk_confirm:
            self._confirm_bulk_delete(links)
            return
        self._do_bm_remove(links)

    def _confirm_bulk_delete(self, links):
        dlg = Gtk.Window(title="Confirm delete", modal=True, transient_for=self)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_top(16); box.set_margin_bottom(16)
        box.set_margin_start(16); box.set_margin_end(16)
        box.append(Gtk.Label(label=f"Delete {len(links)} bookmarks?", xalign=0))
        chk = Gtk.CheckButton(label="Don't ask again")
        box.append(chk)
        btns = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8,
                       halign=Gtk.Align.END)
        cancel = Gtk.Button(label="Cancel")
        delete = Gtk.Button(label="Delete")
        delete.add_css_class("destructive-action")
        btns.append(cancel)
        btns.append(delete)
        box.append(btns)
        dlg.set_child(box)
        cancel.connect("clicked", lambda *_: dlg.destroy())

        def do_delete(*_):
            if chk.get_active():
                self._bm_bulk_confirm = False
                self._save_settings()
            dlg.destroy()
            self._do_bm_remove(links)

        delete.connect("clicked", do_delete)
        dlg.present()

    def _do_bm_remove(self, links):
        self._bm_undo_data = [r for r in self._bm_data if r[2] in links]
        self._bm_data      = [r for r in self._bm_data if r[2] not in links]
        self._bm_refresh()
        for link in links:
            self._mark_result_unbookmarked(link)
        self._write_bookmarks()
        self._set_status(S["bm_removed"])
        if hasattr(self, "_undo_btn"):
            self._undo_btn.set_visible(True)   # undo button built in Step 6

    def _bm_remove_by_link(self, link: str):
        self._bm_data = [r for r in self._bm_data if r[2] != link]
        self._bm_refresh()
        self._mark_result_unbookmarked(link)
        self._write_bookmarks()
        self._set_status(S["bm_removed"])

    def _bm_undo(self, *_):
        if not self._bm_undo_data:
            return
        self._bm_data.extend(self._bm_undo_data)
        self._bm_undo_data = []
        self._bm_refresh()
        self._write_bookmarks()
        if hasattr(self, "_undo_btn"):
            self._undo_btn.set_visible(False)
        self._set_status("Undo: bookmark(s) restored.")

    def _bm_selected_links(self) -> set:
        return {it.link for it in self._selected_items(self._bm_selection)}

    def _on_bm_activate(self, _cv, position):
        item = self._bm_selection.get_item(position)
        if item is not None:
            self._open_url(item.link)

    # ── History ───────────────────────────────────────────────────────────────
    def _log_history(self, query: str):
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(HISTORY_FILE, "a") as f:
            f.write(f"{ts} - {query}\n")
        self._hist_store.insert(0, HistoryItem(ts, query))   # newest at top
        if hasattr(self, "_completion_store"):
            self._completion_add(query)             # completion built in Step 5

    def _load_history(self):
        self._hist_store.remove_all()
        if not os.path.exists(HISTORY_FILE):
            return
        rows = []
        with open(HISTORY_FILE) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    ts, query = line.split(" - ", 1)
                    rows.append((ts, query))
                except Exception:
                    pass
        # reverse so newest appears first
        for ts, query in reversed(rows):
            self._hist_store.append(HistoryItem(ts, query))

    def _hist_rerun(self, *_):
        item = self._hist_selection.get_selected_item()
        if item is not None:
            self._entry.set_text(item.query)
            self._on_search()
            self._notebook.set_current_page(0)

    def _hist_clear(self, *_):
        self._hist_store.remove_all()
        open(HISTORY_FILE, "w").close()
        # Reset completion to seeds only (completion built in Step 5)
        if hasattr(self, "_completion_store"):
            self._completion_store.clear()
            self._completion_seen.clear()
            for term in _SEED_TERMS:
                key = term.lower()
                if key not in self._completion_seen:
                    self._completion_seen.add(key)
                    self._completion_store.append([term])

    def _on_hist_activate(self, _cv, position):
        item = self._hist_selection.get_item(position)
        if item is not None:
            self._entry.set_text(item.query)
            self._on_search()
            self._notebook.set_current_page(0)

    # ── Autocomplete ──────────────────────────────────────────────────────────
    def _build_completion(self) -> Gtk.EntryCompletion:
        """Build EntryCompletion from seed terms + existing history (deduplicated)."""
        self._completion_store = Gtk.ListStore(str)
        self._completion_seen: set[str] = set()

        # Seeds first — provide value even on a fresh install
        for term in _SEED_TERMS:
            key = term.lower()
            if key not in self._completion_seen:
                self._completion_seen.add(key)
                self._completion_store.append([term])

        # History on top of seeds — personal terms override nothing, just dedup
        if os.path.exists(HISTORY_FILE):
            try:
                with open(HISTORY_FILE) as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            _, query = line.split(" - ", 1)
                            self._completion_add(query)
                        except Exception:
                            pass
            except Exception:
                pass

        completion = Gtk.EntryCompletion()
        completion.set_model(self._completion_store)
        completion.set_minimum_key_length(2)
        completion.set_inline_completion(False)
        completion.set_popup_set_width(True)
        completion.set_popup_completion(True)
        completion.set_match_func(self._completion_match)
        completion.connect("match-selected", self._on_completion_selected)

        # Ellipsize long titles so the popup never exceeds the window width
        renderer = Gtk.CellRendererText()
        renderer.set_property("ellipsize", Pango.EllipsizeMode.END)
        completion.pack_start(renderer, True)
        completion.add_attribute(renderer, "text", 0)

        return completion

    def _completion_match(self, completion, typed_key, it):
        if not typed_key.endswith(' '):
            return False
        text = self._completion_store.get_value(it, 0).lower()
        return all(word in text for word in typed_key.split())

    def _completion_add(self, query: str):
        """Add a query to the completion model if not already present."""
        key = query.strip().lower()
        if key and key not in self._completion_seen:
            self._completion_seen.add(key)
            self._completion_store.prepend([query.strip()])  # newest at top

    def _on_completion_selected(self, completion, model, it):
        """User picked a suggestion — fill entry and fire search immediately."""
        term = model.get_value(it, 0)
        self._entry.set_text(term)
        self._on_search()
        return True   # prevent default handler from overwriting the entry

    # ── Live suggestions ──────────────────────────────────────────────────────
    def _on_entry_changed(self, entry):
        """Debounce: schedule live suggestion fetch 400ms after last keystroke."""
        if not hasattr(self, "_completion_store"):
            return  # live suggestions not built yet (Step 5)
        text = entry.get_text().strip()

        # Cancel any pending timer
        if self._suggest_timer is not None:
            GLib.source_remove(self._suggest_timer)
            self._suggest_timer = None

        if len(text) < 3 or self._busy:
            return

        self._suggest_timer = GLib.timeout_add(
            _SUGGEST_DELAY, self._fire_suggestions, text
        )

    def _fire_suggestions(self, term: str):
        """Called by GLib timer — increment token and launch background thread."""
        self._suggest_timer = None
        self._suggest_token += 1
        token = self._suggest_token

        active = [
            f for f in FORUMS
            if self._checks[f["name"]].get_active()
            and f["type"] in _SUGGESTERS
        ]
        if not active:
            return False

        self._suggest_lbl.show()
        threading.Thread(
            target=self._suggestions_thread,
            args=(term, token, active),
            daemon=True,
        ).start()
        return False   # don't repeat the GLib timer

    def _suggestions_thread(self, term: str, token: int, forums: list):
        """Background: fetch suggestions from each active forum, deduplicated."""
        seen:    set[str]  = set()
        results: list[str] = []
        for f in forums:
            suggester = _SUGGESTERS[f["type"]]
            for title in suggester(f, term):
                key = title.lower()
                if key not in seen:
                    seen.add(key)
                    results.append(title)
        GLib.idle_add(self._apply_live_suggestions, results, token)

    def _apply_live_suggestions(self, suggestions: list[str], token: int):
        """Main thread: replace previous live suggestions with new ones."""
        if token != self._suggest_token:
            return   # stale — a newer request already fired
        self._suggest_lbl.hide()

        # Remove previous live suggestions from the front of the store
        for _ in range(self._live_count):
            it = self._completion_store.get_iter_first()
            if it:
                self._completion_store.remove(it)
        self._live_count = 0

        # Prepend new live suggestions that aren't already in permanent store
        new_live: list[str] = []
        for s in suggestions:
            if s.lower() not in self._completion_seen:
                new_live.append(s)

        # Insert in reverse so first result ends up at top
        for s in reversed(new_live):
            self._completion_store.prepend([s])
        self._live_count = len(new_live)

        # Force the popup to appear with the new suggestions
        if new_live:
            self._entry.get_completion().complete()

    # ── Tooltip ───────────────────────────────────────────────────────────────
    def _on_result_hover(self, widget, event):
        info = widget.get_path_at_pos(int(event.x), int(event.y))
        if not info:
            self._on_result_hover_leave()
            return False
        it   = self._res_store.get_iter(info[0])
        link = self._res_store.get_value(it, 4)
        if link != self._hover_link:
            self._hover_link = link
            self._statusbar.pop(self._hover_ctx)
            self._statusbar.push(self._hover_ctx, link)
        return False

    def _on_result_hover_leave(self, *_):
        self._hover_link = None
        self._statusbar.pop(self._hover_ctx)

    # ── Keyboard shortcuts ────────────────────────────────────────────────────
    def _on_key_press(self, _widget, event):
        key  = event.keyval
        ctrl = event.state & Gdk.ModifierType.CONTROL_MASK

        if ctrl and key == Gdk.KEY_Tab:
            n = self._notebook.get_n_pages()
            self._notebook.set_current_page((self._notebook.get_current_page() + 1) % n)
            return True
        if ctrl and key == Gdk.KEY_ISO_Left_Tab:
            n = self._notebook.get_n_pages()
            self._notebook.set_current_page((self._notebook.get_current_page() - 1) % n)
            return True
        if ctrl and key == Gdk.KEY_l:
            self._entry.grab_focus()
            self._entry.select_region(0, -1)
            return True
        if ctrl and key == Gdk.KEY_f:
            self._toggle_forums_bar()
            return True
        if key == Gdk.KEY_Escape:
            self._entry.set_text("")
            self._entry.grab_focus()
            return True
        if key == Gdk.KEY_F5:
            self._on_search()
            return True
        if ctrl and key == Gdk.KEY_z:
            self._bm_undo()
            return True
        if key == Gdk.KEY_F6:
            self._focus_active_table()
            return True
        if key == Gdk.KEY_Return and not self._entry.has_focus():
            if self._notebook.get_current_page() == 0:
                _, paths = self._res_view.get_selection().get_selected_rows()
                if len(paths) > 1:
                    self._open_results_multi(paths)
                    return True
            return False
        if ctrl and key == Gdk.KEY_Return:
            if self._notebook.get_current_page() == 0 and not self._entry.has_focus():
                _, paths = self._res_view.get_selection().get_selected_rows()
                if paths:
                    self._open_results_multi(paths)
            return True
        if ctrl and key == Gdk.KEY_b:
            if self._notebook.get_current_page() == 0 and not self._entry.has_focus():
                model, paths = self._res_view.get_selection().get_selected_rows()
                if paths:
                    bm_urls = self._bookmarked_urls()
                    links   = [model.get_value(model.get_iter(p), 4) for p in paths]
                    if all(l in bm_urls for l in links):
                        self._unbookmark_results_multi(paths)
                    else:
                        self._bookmark_results_multi(paths)
            return True
        if key == Gdk.KEY_question and not self._entry.has_focus():
            self._show_shortcuts(self._help_btn)
            return True
        return False

    def _focus_active_table(self):
        self._entry.get_completion().complete()  # collapse any open popup
        page  = self._notebook.get_current_page()
        views = [self._res_view, self._bm_view, self._hist_view]
        if page >= len(views):
            return
        view = views[page]
        view.grab_focus()
        sel = view.get_selection()
        if sel.count_selected_rows() == 0:
            it = view.get_model().get_iter_first()
            if it:
                sel.select_iter(it)
                path = view.get_model().get_path(it)
                view.scroll_to_cell(path, None, True, 0.0, 0.0)

    # ── Settings persist ──────────────────────────────────────────────────────
    def _load_settings(self):
        try:
            with open(SETTINGS_FILE) as f:
                cfg = json.load(f)
            w = cfg.get("width",  960)
            h = cfg.get("height", 640)
            self.resize(w, h)
            self._hits_spin.set_value(cfg.get("hits", DEFAULT_HITS))
            self._forums_bar_visible = cfg.get("forums_bar_visible", True)
            self._bm_bulk_confirm    = cfg.get("bm_bulk_confirm", True)
            for name, state in cfg.get("forums", {}).items():
                if name in self._checks:
                    self._checks[name].set_active(state)
        except Exception:
            pass   # first run or corrupt file — silently use defaults

    def _save_settings(self):
        try:
            w, h = self.get_size()
            cfg = {
                "width":              w,
                "height":             h,
                "hits":               int(self._hits_spin.get_value()),
                "forums_bar_visible": self._forums_bar_visible,
                "bm_bulk_confirm":    self._bm_bulk_confirm,
                "forums":             {n: cb.get_active() for n, cb in self._checks.items()},
            }
            with open(SETTINGS_FILE, "w") as f:
                json.dump(cfg, f, indent=2)
        except Exception:
            pass

    def _on_delete(self, *_):
        self._save_settings()
        return False   # let the destroy signal proceed

    # ── Helpers ───────────────────────────────────────────────────────────────
    @staticmethod
    def _open_url(url: str):
        subprocess.Popen(["xdg-open", url],
                         stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)

    @staticmethod
    def _copy(text: str):
        Gdk.Display.get_default().get_clipboard().set(text)


# ─── Entry point ──────────────────────────────────────────────────────────────
def on_activate(app):
    ScoutWindow(app)

if __name__ == "__main__":
    GLib.set_prgname("forum-scout")
    app = Gtk.Application(application_id="org.musqz.forum-scout")
    app.connect("activate", on_activate)
    app.run(None)
