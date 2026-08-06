# -*- coding: utf-8 -*-
"""Mutating WickedWhims' picker dialogs.

The settings menus are one UI family; picker dialogs are the other, and most
of WickedWhims lives here -- the body selector, the animation pickers, the sim
pickers, playlists. They are built from `turbolib2.ui.object_picker_dialog`:

    TurboObjectPickerDialog
        picker_rows                  dict: state -> [TurboObjectPickerRow]
        add_picker_row(state, *rows) appends
        display(self, client_sim)    shows it

`display` is the analogue of SettingsWindow.open: it runs once, after every
row has been added, with the whole set in hand. So the same set arithmetic
applies and for the same reasons:

    shown = (base - (removals - reservations)) + upserts

Two things are easier here than in the settings menus. Rows carry their own
identity (`get_identifier`, `get_tag`), so nothing has to be addressed by
position. And dispatch is by row identifier rather than list index, so a
mutation cannot make one row fire another -- the failure that made the
settings hook delicate.

Dialogs are told apart by `title`, which is a localised-string KEY rather than
display text, so matching on it is language-stable.
"""

from . import compat, events

ANY_DIALOG = None

_observed = {}       # title -> [row identity]
_bases = {}          # id(dialog) is useless across opens; keyed by title
_removals = {}
_reservations = {}
_upserts = {}
_next_token = [0]

_counts = {'displays': 0, 'removed': 0, 'reserved': 0, 'added': 0,
           'failed': 0, 'dynamic_failed': 0, 'errors': 0, 'routed': 0}
_shapes = {}
_last_error = [None]
_title_source = {}
_row_names = {}
_installed = []


def _token():
    _next_token[0] += 1
    return _next_token[0]


def _owner(depth=3):
    import sys
    try:
        return sys._getframe(depth).f_globals.get('__name__', '?').split('.')[0]
    except Exception:
        return '?'


# --------------------------------------------------------------------------
# identity
# --------------------------------------------------------------------------
def row_key(row):
    """A stable handle for one row, or None.

    None never matches -- several rows in one dialog can lack identity, and
    treating None as a value would make them all compare equal. That mistake
    once removed every unkeyed element in a settings window at once.
    """
    for name in ('get_identifier', 'get_tag'):
        getter = getattr(row, name, None)
        if getter is None:
            continue
        try:
            value = getter()
        except Exception:
            continue
        if value is not None:
            return value
    getter = getattr(row, 'get_name', None)
    if getter is not None:
        try:
            return getter()
        except Exception:
            pass
    return None


def _row_name(row):
    """Whatever a row calls itself, for the listing.

    Identifiers turned out to be positional (0, 1, 2, 3), so the name is what
    actually tells a reader which row is which.
    """
    for attr in ('get_name', 'get_description'):
        getter = getattr(row, attr, None)
        if getter is None:
            continue
        try:
            value = getter()
        except Exception:
            continue
        if value is not None:
            text = repr(value)
            cut = text.find(' object at 0x')
            return (text[:cut] + '>') if cut != -1 else text[:60]
    return None


def dialog_title(dialog):
    """A stable, hashable identity for a dialog.

    `title` holds the RESOLVED LocalizedString, not the localisation key --
    turbolib2 does self.title = get_l18n_service().get_localized_string(...).
    That object is a protocol buffer: unhashable, and its repr carries a
    memory address that changes every run, so neither the object nor its repr
    can identify a dialog across sessions.

    The protobuf does carry the string hash as a field, and that IS stable and
    language-independent, so it is preferred. Everything after it is a
    fallback that keeps the bridge working while making the degradation
    visible in the report.
    """
    raw = getattr(dialog, 'title', None)
    if raw is None:
        return None
    for attr in ('hash', 'string_hash', 'key'):
        try:
            value = getattr(raw, attr, None)
        except Exception:
            continue
        if isinstance(value, int) and value:
            _title_source['hash'] = _title_source.get('hash', 0) + 1
            return value
    try:
        hash(raw)
        _title_source['object'] = _title_source.get('object', 0) + 1
        return raw
    except Exception:
        pass
    # Last resort: repr with the address stripped, so at least it is stable
    # within a session. Distinct dialogs may collide here, which is why the
    # report says how many titles came from this branch.
    _title_source['repr'] = _title_source.get('repr', 0) + 1
    text = repr(raw)
    cut = text.find(' object at 0x')
    return (text[:cut] + '>') if cut != -1 else text[:120]


def _matches(match, row, index=None):
    if callable(match):
        try:
            return bool(match(row))
        except Exception:
            return False
    if isinstance(match, tuple) and len(match) == 2 and match[0] == '#':
        return index == match[1]
    if match is None:
        return False
    key = row_key(row)
    return key is not None and key == match


def _title_matches(declared, title):
    return declared is ANY_DIALOG or declared == title


# --------------------------------------------------------------------------
# declarations
# --------------------------------------------------------------------------
def _declare(table, kind, title, match, reason):
    token = _token()
    table.setdefault((title, match), []).append((token, _owner(3), reason))
    return (kind, title, match, token)


def remove(title, match, reason=None):
    """Take a row out of a dialog. ANY_DIALOG matches wherever it appears."""
    return _declare(_removals, 'remove', title, match, reason)


def reserve(title, match, reason=None):
    """Keep a row another mod asked to remove. Reserve wins."""
    return _declare(_reservations, 'reserve', title, match, reason)


def upsert(title, factory, key=None, order=None, reason=None, on_select=None,
           tag=None):
    """Add a row. `factory(dialog, state)` returns a TurboObjectPickerRow.

    `on_select(tag, dialog)` is called when the player picks this row, and
    `tag` is the value the row was built with. This matters because
    _dialog_response hands WickedWhims' own callback get_result_tags() -- the
    row TAG, not its identifier -- so an added row would otherwise deliver a
    tag WickedWhims has no idea what to do with. Supplying on_select makes the
    bridge intercept that tag and route it here instead, passing everything
    else through untouched.

    See `row_classes()` for the constructor, so a consuming mod never imports
    from turbolib2 itself.
    """
    owner = _owner()
    if key is None:
        key = '%s#%d' % (owner, len(_upserts))
    _upserts[(title, key)] = dict(factory=factory, owner=owner, reason=reason,
                                  order=order, on_select=on_select, tag=tag)
    return ('upsert', title, key)


def withdraw(handle):
    if not handle or len(handle) < 3:
        return False
    kind = handle[0]
    if kind == 'upsert':
        return _upserts.pop((handle[1], handle[2]), None) is not None
    table = {'remove': _removals, 'reserve': _reservations}.get(kind)
    if table is None:
        return False
    key = (handle[1], handle[2])
    holders = table.get(key)
    if not holders:
        return False
    remaining = [h for h in holders if h[0] != handle[3]]
    if len(remaining) == len(holders):
        return False
    if remaining:
        table[key] = remaining
    else:
        del table[key]
    return True


# --------------------------------------------------------------------------
# application
# --------------------------------------------------------------------------
def _effective_rows(dialog):
    """Every row this dialog is about to show, from both sources.

    Rows arrive two ways: a static picker_rows dict, and a
    dynamic_picker_rows_func the dialog calls at build time. The body selector
    uses the dynamic one, which is why hooking display() and reading
    picker_rows saw nothing at all.
    """
    rows = []
    state = getattr(dialog, 'picker_rows_state', None)
    func = getattr(dialog, 'dynamic_picker_rows_func', None)
    if func is not None:
        try:
            produced = func(state)
            if produced:
                rows.extend(produced)
        except Exception:
            _counts['dynamic_failed'] += 1
    static = getattr(dialog, 'picker_rows', None)
    if isinstance(static, dict):
        try:
            rows.extend(static.get(state) or [])
        except Exception:
            pass
    return state, rows


def _apply(dialog):
    """Materialise, mutate, and hand the result back as static rows.

    The dynamic function is consumed here and cleared for the duration of the
    build so the original does not add everything twice; it is restored
    immediately afterwards so later rebuilds still work.
    """
    title = dialog_title(dialog)
    state, rows = _effective_rows(dialog)

    seen = [row_key(r) for r in rows]
    _row_names[title] = [_row_name(r) for r in rows]
    fresh = title not in _observed
    _observed[title] = seen
    if not rows:
        # Record the shape, so an unexpected dialog is diagnosable rather than
        # silently skipped -- the failure that cost a round trip here.
        _shapes[title] = sorted(a for a in dir(dialog)
                                if not a.startswith('__'))[:24]

    kept = []
    for position, row in enumerate(rows):
        drop = False
        for (t, match), _askers in _removals.items():
            if not _title_matches(t, title) or not _matches(match, row, position):
                continue
            reserved = any(_title_matches(rt, title) and _matches(rm, row, position)
                           for (rt, rm) in _reservations)
            if reserved:
                _counts['reserved'] += 1
            else:
                drop = True
            break
        if drop:
            _counts['removed'] += 1
            continue
        kept.append(row)

    additions = [(k, spec) for k, spec in _upserts.items()
                 if _title_matches(k[0], title)]
    additions.sort(key=lambda item: (item[1]['order'] is None,
                                     item[1]['order'], item[1]['owner'],
                                     str(item[0][1])))
    routes = {}
    for _key, spec in additions:
        try:
            row = spec['factory'](dialog, state)
        except Exception:
            _counts['failed'] += 1
            continue
        if row is None:
            continue
        kept.append(row)
        _counts['added'] += 1
        if spec.get('on_select') is not None:
            tag = spec.get('tag')
            if tag is None:
                getter = getattr(row, 'get_tag', None)
                try:
                    tag = getter() if getter else None
                except Exception:
                    tag = None
            if tag is not None:
                routes[tag] = spec['on_select']

    static = getattr(dialog, 'picker_rows', None)
    if isinstance(static, dict):
        static[state] = kept
    _route_callback(dialog, routes)
    if fresh:
        try:
            from . import bootstrap
            bootstrap.write_report()
        except Exception:
            pass


def _route_callback(dialog, routes):
    """Intercept selections of rows we added, pass everything else through.

    WickedWhims' callback receives the selected row TAGS. A tag it did not
    create means nothing to it, so ours are pulled out first. The wrapper is
    marked to survive repeated builds without stacking.
    """
    if not routes:
        return
    original = getattr(dialog, 'callback', None)
    if original is None:
        return
    if getattr(original, '_wickedbridge_routed', False):
        original._wickedbridge_routes.update(routes)
        return

    table = dict(routes)

    def _callback(result=None, *args, **kwargs):
        try:
            tags = result if isinstance(result, (list, tuple, set)) else [result]
            for tag in tags:
                handler = table.get(tag)
                if handler is not None:
                    _counts['routed'] += 1
                    try:
                        return handler(tag, dialog)
                    except Exception as ex:
                        _counts['errors'] += 1
                        _last_error[0] = 'on_select raised: %r' % (ex,)
                        return None
        except Exception:
            pass
        return original(result, *args, **kwargs)

    _callback._wickedbridge_routed = True
    _callback._wickedbridge_routes = table
    try:
        dialog.callback = _callback
    except Exception:
        _counts['errors'] += 1
        _last_error[0] = 'could not wrap dialog callback'


def install():
    """Wrap TurboObjectPickerDialog.display. Idempotent."""
    if _installed:
        return list(_installed)
    cls = compat.get('TurboObjectPickerDialog')
    if cls is None:
        return []
    # _build_dialog_picker_rows, not display: it is where BOTH row sources are
    # combined, and the last point before rows are pushed into EA's dialog.
    # display() runs earlier, before the dynamic rows exist.
    original = getattr(cls, '_build_dialog_picker_rows', None)
    if original is None or getattr(original, '_wickedbridge_dlg', False):
        return []

    def _build(self, *args, **kwargs):
        restore = getattr(self, 'dynamic_picker_rows_func', None)
        try:
            _counts['displays'] += 1
            _apply(self)
            # Cleared so the original does not add the dynamic rows a second
            # time on top of the list we just wrote.
            self.dynamic_picker_rows_func = None
        except Exception as ex:
            # Recorded, never silent. A swallowed exception here once produced
            # 'one display, zero dialogs seen' and no way to tell why.
            _counts['errors'] += 1
            _last_error[0] = '%r on %r' % (ex, getattr(self, 'title', None))
        try:
            return original(self, *args, **kwargs)
        finally:
            try:
                self.dynamic_picker_rows_func = restore
            except Exception:
                pass

    _build._wickedbridge_dlg = True
    try:
        cls._build_dialog_picker_rows = _build
    except Exception:
        return []
    _installed.append('dialogs')
    return list(_installed)


# --------------------------------------------------------------------------
def row_classes():
    """turbolib2's row constructors, so a consumer imports nothing."""
    names = ('TurboObjectPickerRow', 'TurboPickerCategory')
    return dict((n, compat.get(n)) for n in names if compat.get(n) is not None)


def observed():
    """Dialog titles seen, and the row identities each shipped with.

    Titles are localised-string keys, not text -- so this is how a mod author
    finds the number to address, exactly like the settings listing.
    """
    return dict((k, list(v)) for k, v in _observed.items())


def listing():
    lines = []
    index = {}
    for d, title in enumerate(sorted(_observed, key=lambda k: str(k))):
        keys = _observed[title]
        lines.append('[d%d] dialog %r  (%d rows)' % (d, title, len(keys)))
        for r, key in enumerate(keys):
            unique = key is not None and keys.count(key) == 1
            index['d%d.%d' % (d, r)] = (title, key if unique else ('#', r), r)
            names = _row_names.get(title) or []
            label = names[r] if r < len(names) else None
            lines.append('       [d%d.%d] %-10r %s%s'
                         % (d, r, key, label or '',
                            '' if unique else '   <- addressed by position'))
    return lines, index


def mutations():
    out = []
    for (title, match), askers in _removals.items():
        reserved = [1 for (t, m) in _reservations if t == title and m == match]
        out.append(dict(kind='remove', dialog=title, match=match,
                        owners=[o for _t, o, _r in askers],
                        outcome='vetoed by reservation' if reserved else 'removed'))
    for (title, key), spec in _upserts.items():
        out.append(dict(kind='upsert', dialog=title, match=key,
                        owners=[spec['owner']], outcome='added'))
    return out


def report_lines():
    lines = ['picker dialogs: %s, displays=%d'
             % ('on' if _installed else 'OFF', _counts['displays']),
             '   removed=%d reserved=%d added=%d routed=%d factory errors=%d'
             % (_counts['removed'], _counts['reserved'], _counts['added'],
                _counts['routed'], _counts['failed'])]
    for entry in mutations():
        lines.append('   %-7s %-20s %-18s by %s -- %s'
                     % (entry['kind'], str(entry['dialog'])[:20],
                        str(entry['match'])[:18],
                        ', '.join(entry['owners']), entry['outcome']))
    if _observed:
        lines.append('')
        lines.append('   picker dialogs seen (%d):' % len(_observed))
        for line in listing()[0]:
            lines.append('   ' + line)
    else:
        lines.append('   no picker dialogs seen yet -- open one and look again')
    for title, attrs in _shapes.items():
        lines.append('   dialog %r produced NO rows -- attributes: %s'
                     % (title, ', '.join(attrs)))
    if _counts['dynamic_failed']:
        lines.append('   %d dynamic row functions raised' % _counts['dynamic_failed'])
    if _title_source:
        lines.append('   dialog identity came from: %s' % _title_source)
        if _title_source.get('repr'):
            lines.append('   WARNING %d dialogs identified only by repr -- '
                         'distinct dialogs can collide there'
                         % _title_source['repr'])
    if _last_error[0]:
        lines.append('   LAST ERROR building a dialog: %s' % _last_error[0])
    if _counts['displays'] and not _observed and not _last_error[0]:
        lines.append('   %d dialogs were built but none recorded, and nothing '
                     'raised -- the shape is unexpected in a new way'
                     % _counts['displays'])
    return lines
