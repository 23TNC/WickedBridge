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

_counts = {'displays': 0, 'removed': 0, 'reserved': 0, 'added': 0, 'failed': 0}
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


def dialog_title(dialog):
    return getattr(dialog, 'title', None)


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


def upsert(title, factory, key=None, order=None, reason=None):
    """Add a row. `factory(dialog, state)` returns a TurboObjectPickerRow.

    See `row_classes()` for the constructor, so a consuming mod never imports
    from turbolib2 itself.
    """
    owner = _owner()
    if key is None:
        key = '%s#%d' % (owner, len(_upserts))
    _upserts[(title, key)] = dict(factory=factory, owner=owner, reason=reason,
                                  order=order)
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
def _apply(dialog):
    title = dialog_title(dialog)
    rows_by_state = getattr(dialog, 'picker_rows', None)
    if not isinstance(rows_by_state, dict):
        return

    base = getattr(dialog, '_wickedbridge_base', None)
    if base is None:
        base = dict((state, list(rows)) for state, rows in rows_by_state.items())
        dialog._wickedbridge_base = base

    seen = []
    for state, rows in base.items():
        kept = []
        for position, row in enumerate(rows):
            seen.append(row_key(row))
            drop = False
            for (t, match), _askers in _removals.items():
                if not _title_matches(t, title) or not _matches(match, row, position):
                    continue
                reserved = any(_title_matches(rt, title)
                               and _matches(rm, row, position)
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
        for _key, spec in additions:
            try:
                row = spec['factory'](dialog, state)
            except Exception:
                _counts['failed'] += 1
                continue
            if row is not None:
                kept.append(row)
                _counts['added'] += 1
        rows_by_state[state] = kept

    _observed[title] = seen


def install():
    """Wrap TurboObjectPickerDialog.display. Idempotent."""
    if _installed:
        return list(_installed)
    cls = compat.get('TurboObjectPickerDialog')
    if cls is None:
        return []
    original = getattr(cls, 'display', None)
    if original is None or getattr(original, '_wickedbridge_dlg', False):
        return []

    def _display(self, *args, **kwargs):
        try:
            _counts['displays'] += 1
            _apply(self)
        except Exception:
            # Never stop a dialog opening because a declaration misbehaved.
            pass
        return original(self, *args, **kwargs)

    _display._wickedbridge_dlg = True
    try:
        cls.display = _display
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
            lines.append('       [d%d.%d] %r%s'
                         % (d, r, key,
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
             '   removed=%d reserved=%d added=%d factory errors=%d'
             % (_counts['removed'], _counts['reserved'],
                _counts['added'], _counts['failed'])]
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
    return lines
