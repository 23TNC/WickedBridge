# -*- coding: utf-8 -*-
"""Mutating WickedWhims' settings menus.

WickedWhims builds each settings screen as a `SettingsWindow` holding a plain
list of elements, and opens it with:

    self._update_settings_options()
    get_dialog_service().display_objects_picker_dialog(
        title=self.title, ..., enumerate(self.elements), ...,
        callback=self._window_callback)

    def _window_callback(self, element_index):
        self.elements[element_index]._select()

Two facts follow, and the whole design rests on them:

  * rows are enumerated AT OPEN, from the live list -- so mutating `elements`
    before the original open() runs keeps row ids and list indices consistent
    by construction, with no renumbering to do;
  * dispatch is BY INDEX -- so mutating the list while a dialog is on screen
    would fire the wrong item. Mutations are therefore applied only on the way
    into open(), never at any other time.

The mutation model is set arithmetic, so the resulting menu is a pure function
of what every mod declared and does NOT depend on which mod loaded first:

    shown = (base - (removals - reservations)) + upserts

  remove    idempotent. Five mods removing one node agree; there is nothing to
            arbitrate.
  reserve   vetoes a removal. Reserve wins, because retention is the
            conservative outcome and fails visibly -- a menu someone wanted
            gone is still there and `mutations()` says why, whereas the
            opposite silently strips a mod of something it depends on.
  upsert    keyed, and the key is namespaced to the owning mod unless it says
            otherwise -- so two mods adding to the same window produce a union
            rather than clobbering each other.

Nothing here decides policy. Whether to strip a WickedWhims branch or leave it
alongside your own is the consuming mod's call; this only makes both
expressible and records who asked for what.
"""

from . import compat, events

# window_id -> element identities seen in the untouched window. Populated as
# windows open, because the ids cannot be known ahead of time -- discovery is a
# runtime activity, and `observed()` is how a mod author finds what to address.
_observed = {}

# (window_id, match) -> [(token, owner, reason)]. A list, because several mods
# may declare the same thing and withdrawing one must not drop the others.
_removals = {}
_reservations = {}
_upserts = {}        # (window_id, key) -> dict(factory, owner, reason, order)

_next_token = [0]


def _token():
    _next_token[0] += 1
    return _next_token[0]

_counts = {'opens': 0, 'removed': 0, 'reserved': 0, 'added': 0, 'failed': 0}
_installed = []


# --------------------------------------------------------------------------
# identity
# --------------------------------------------------------------------------
def element_key(element):
    """A stable handle for one element.

    `setting_identifier` when the element has one, else `option_name` -- which
    is a localised-string KEY, not display text, so it does not shift with the
    player's language.
    """
    for attr in ('setting_identifier', 'option_name'):
        value = getattr(element, attr, None)
        if value is not None:
            return value
    return None


def _matches(match, element):
    """`match` is an element key, or a predicate over the element."""
    if callable(match):
        try:
            return bool(match(element))
        except Exception:
            return False
    return element_key(element) == match


def _owner(depth=2):
    """Infer the calling mod, so nothing has to name itself."""
    import sys
    try:
        frame = sys._getframe(depth)
        return frame.f_globals.get('__name__', '?').split('.')[0]
    except Exception:
        return '?'


# --------------------------------------------------------------------------
# declarations
# --------------------------------------------------------------------------
def _declare(table, kind, window_id, match, reason):
    token = _token()
    table.setdefault((window_id, match), []).append((token, _owner(3), reason))
    # The kind is part of the handle: remove and reserve address the same node
    # and would otherwise be indistinguishable, so withdrawing a reservation
    # could delete the removal instead.
    return (kind, window_id, match, token)


def remove(window_id, match, reason=None):
    """Take a node out of a window. Idempotent across mods."""
    return _declare(_removals, 'remove', window_id, match, reason)


def reserve(window_id, match, reason=None):
    """Keep a node that another mod asked to remove. Reserve wins."""
    return _declare(_reservations, 'reserve', window_id, match, reason)


def upsert(window_id, factory, key=None, order=None, reason=None):
    """Add or update a node.

    `factory()` is called on each open and must return a WickedWhims settings
    element -- see `classes()` for the constructors, so a consuming mod never
    has to import from wickedwhims itself.

    `key` defaults to one namespaced by the calling mod, which is what makes
    several mods adding to one window produce a union. Pass an explicit key
    only to cooperate deliberately with a mod that uses the same one.
    """
    owner = _owner()
    if key is None:
        key = '%s#%d' % (owner, len(_upserts))
    _upserts[(window_id, key)] = dict(factory=factory, owner=owner,
                                      reason=reason, order=order)
    return ('upsert', window_id, key)


def withdraw(handle):
    """Drop one declaration. Returns True if anything was dropped.

    Only the declaration this handle names -- another mod that asked for the
    same thing keeps its own, which is what stops one mod's cleanup silently
    undoing another's intent.
    """
    if not handle or len(handle) < 3:
        return False
    kind = handle[0]
    if kind == 'upsert':
        return _upserts.pop((handle[1], handle[2]), None) is not None
    table = {'remove': _removals, 'reserve': _reservations}.get(kind)
    if table is None:
        return False
    key = (handle[1], handle[2])
    askers = table.get(key)
    if not askers:
        return False
    remaining = [a for a in askers if a[0] != handle[3]]
    if len(remaining) == len(askers):
        return False
    if remaining:
        table[key] = remaining
    else:
        del table[key]
    return True


# --------------------------------------------------------------------------
# application
# --------------------------------------------------------------------------
def _apply(window):
    """Rebuild window.elements from the untouched base plus declarations.

    Recomputed from the stored base every time rather than edited in place, so
    reopening a window cannot compound edits and a withdrawn declaration
    actually disappears.
    """
    window_id = getattr(window, 'window_id', None)
    base = getattr(window, '_wickedbridge_base', None)
    if base is None:
        base = list(getattr(window, 'elements', []))
        window._wickedbridge_base = base

    _observed[window_id] = [element_key(e) for e in base]

    kept = []
    for element in base:
        drop = False
        for (wid, match), askers in _removals.items():
            if wid != window_id or not _matches(match, element):
                continue
            # Reserve wins: a single reservation outranks any number of
            # removals, because keeping a node is the recoverable outcome.
            reserved = any(w == window_id and _matches(m, element)
                           for (w, m) in _reservations)
            if reserved:
                _counts['reserved'] += 1
            else:
                drop = True
            break
        if drop:
            _counts['removed'] += 1
            continue
        kept.append(element)

    # Deterministic order: explicit `order`, then owner name. Registration
    # order would make the menu reshuffle with script load order.
    additions = [(k, spec) for k, spec in _upserts.items() if k[0] == window_id]
    additions.sort(key=lambda item: (item[1]['order'] is None,
                                     item[1]['order'], item[1]['owner'],
                                     str(item[0][1])))
    for _key, spec in additions:
        try:
            element = spec['factory']()
        except Exception:
            _counts['failed'] += 1
            continue
        if element is not None:
            kept.append(element)
            _counts['added'] += 1

    window.elements = kept


def install():
    """Wrap SettingsWindow.open. Idempotent.

    A class attribute, so one assignment reaches every window including ones
    built later -- no walking sys.modules for holders.
    """
    if _installed:
        return list(_installed)
    window_cls = compat.get('SettingsWindow')
    if window_cls is None:
        return []
    original = getattr(window_cls, 'open', None)
    if original is None or getattr(original, '_wickedbridge_menu', False):
        return []

    def _open(self, *args, **kwargs):
        try:
            _counts['opens'] += 1
            _apply(self)
        except Exception:
            # Never stop a player reaching WickedWhims' own settings because a
            # mod's declaration misbehaved.
            pass
        return original(self, *args, **kwargs)

    _open._wickedbridge_menu = True
    try:
        window_cls.open = _open
    except Exception:
        return []
    _installed.append('settings.menu')
    return list(_installed)


# --------------------------------------------------------------------------
# discovery and diagnostics
# --------------------------------------------------------------------------
def classes():
    """WickedWhims' settings element constructors, for building upserts."""
    names = ('SettingsWindow', 'SettingsBranchElement', 'SettingsSwitchElement',
             'SettingsSelectElement', 'SettingsCustomCallbackElement',
             'SettingsInputElement')
    return dict((name, compat.get(name)) for name in names
                if compat.get(name) is not None)


def observed():
    """Every window seen so far, and the element keys it shipped with.

    window_ids cannot be enumerated offline, so this is how a mod author finds
    what to address. It fills in as the player walks the settings tree.
    """
    return dict((k, list(v)) for k, v in _observed.items())


def mutations():
    """Every declaration, and what became of it."""
    out = []
    for (window_id, match), askers in _removals.items():
        reserved = [(w, m) for (w, m) in _reservations
                    if w == window_id and m == match]
        out.append(dict(kind='remove', window=window_id, match=match,
                        owners=[o for _t, o, _r in askers],
                        outcome='vetoed by reservation' if reserved else 'removed'))
    for (window_id, match), askers in _reservations.items():
        out.append(dict(kind='reserve', window=window_id, match=match,
                        owners=[o for _t, o, _r in askers], outcome='retained'))
    for (window_id, key), spec in _upserts.items():
        out.append(dict(kind='upsert', window=window_id, match=key,
                        owners=[spec['owner']], outcome='added'))
    return out


def report_lines():
    lines = ['settings menu: %s, windows opened=%d'
             % ('on' if _installed else 'OFF', _counts['opens']),
             '   removed=%d reserved=%d added=%d factory errors=%d'
             % (_counts['removed'], _counts['reserved'],
                _counts['added'], _counts['failed'])]
    for entry in mutations():
        lines.append('   %-7s %-22s %-18s by %s -- %s'
                     % (entry['kind'], str(entry['window'])[:22],
                        str(entry['match'])[:18],
                        ', '.join(entry['owners']), entry['outcome']))
    if _observed and not mutations():
        lines.append('   %d windows observed, no mutations declared'
                     % len(_observed))
    return lines
