# -*- coding: utf-8 -*-
"""Read WickedWhims settings without importing its enums.

Roughly half of the WickedWhims symbols a mod ends up importing are not events
at all -- they are settings enums and their accessors. Wrapping them here means
a consumer never writes `from wickedwhims.sex.sex_settings import SexSetting`,
which is the coupling the bridge exists to remove.

Settings are addressed by name:

    wickedbridge.settings.sex('CUM_SWITCH_STATE')
    wickedbridge.settings.nudity('NUDITY_SWITCH_STATE')

An unknown name, or a missing WickedWhims accessor, returns the supplied
default rather than raising -- callers should degrade, not crash.
"""

import sys

from . import compat

_DOMAINS = {
    'sex': ('wickedwhims.sex.sex_settings', 'SexSetting', 'get_sex_setting'),
    'nudity': ('wickedwhims.nudity.nudity_settings', 'NuditySetting',
               'get_nudity_setting'),
    'relationship': ('wickedwhims.relationships.relationship_settings',
                     'RelationshipSetting', 'get_relationship_setting'),
}

_misses = {}

# --------------------------------------------------------------------------
# writing: locks
#
# A lock overrides what WickedWhims reports for one setting. Mods declare
# them; the bridge decides what happens when they disagree.
#
#   agreement coalesces   two mods locking the same value both get what they
#                         asked for, and there is nothing to arbitrate
#   disagreement defers   neither applies. The PLAYER's own setting stands and
#                         both claimants are reported. When two mods want
#                         opposite values no configuration satisfies both, so
#                         something is broken either way -- the only choice is
#                         whether it is diagnosable. Picking a winner silently
#                         leaves the loser misbehaving with no signal; falling
#                         back makes the conflict visible and hands the
#                         tiebreak to the human.
#
# Locks are runtime-only and must be re-declared each session. One persisting
# into a save whose mod is gone would be unremovable.
# --------------------------------------------------------------------------
CONFLICT = object()

_locks = {}        # (domain, name) -> [(token, owner, value, reason)]
_effective = {}    # (domain, name) -> value        (conflicts are absent)
_conflicts = {}    # (domain, name) -> [(owner, value)]
_member_cache = {}
_installed = []
_counts = {'reads': 0, 'overridden': 0, 'deferred': 0}
_next_token = [0]


def _token():
    _next_token[0] += 1
    return _next_token[0]


def _owner(depth=3):
    try:
        return sys._getframe(depth).f_globals.get('__name__', '?').split('.')[0]
    except Exception:
        return '?'


def _recompute():
    """Rebuild the effective map. Cheap, and only on declaration changes."""
    _effective.clear()
    _conflicts.clear()
    for key, holders in _locks.items():
        values = set(h[2] for h in holders)
        if len(values) == 1:
            _effective[key] = holders[0][2]
        else:
            _conflicts[key] = [(h[1], h[2]) for h in holders]


def _members(domain):
    """member -> name, so the wrapper can match a member back to a lock.

    WickedWhims' getters take an enum MEMBER; locks are declared by NAME.
    Built once per domain and rebuilt only if the enum was not loaded yet.
    """
    cached = _member_cache.get(domain)
    if cached:
        return cached
    enum, _getter = _lookup(domain)
    if enum is None:
        return {}
    mapping = {}
    for name in dir(enum):
        if not name.isupper():
            continue
        try:
            mapping[getattr(enum, name)] = name
        except Exception:
            continue
    _member_cache[domain] = mapping
    return mapping


def lock(domain, name, value, reason=None):
    """Make WickedWhims report `value` for this setting.

    Returns a handle for unlock(). The owner is inferred from the calling
    module, so nothing has to name itself.
    """
    if domain not in _DOMAINS:
        return None
    token = _token()
    _locks.setdefault((domain, name), []).append((token, _owner(), value, reason))
    _recompute()
    return ('lock', domain, name, token)


def unlock(handle):
    """Drop one lock. Another mod's lock on the same setting is untouched."""
    if not handle or len(handle) != 4 or handle[0] != 'lock':
        return False
    key = (handle[1], handle[2])
    holders = _locks.get(key)
    if not holders:
        return False
    remaining = [h for h in holders if h[0] != handle[3]]
    if len(remaining) == len(holders):
        return False
    if remaining:
        _locks[key] = remaining
    else:
        del _locks[key]
    _recompute()
    return True


def is_locked(domain, name):
    """The effective lock, or None. Returns CONFLICT when mods disagree."""
    key = (domain, name)
    if key in _conflicts:
        return CONFLICT
    return _effective.get(key)


def locks():
    return dict((k, [(o, v, r) for _t, o, v, r in h]) for k, h in _locks.items())


def conflicts():
    return dict(_conflicts)


def install():
    """Wrap each domain getter so locked settings report the locked value."""
    for domain, (_path, _enum, getter_name) in _DOMAINS.items():
        key = {'sex': 'get_sex_setting', 'nudity': 'get_nudity_setting',
               'relationship': 'get_relationship_setting'}[domain]
        if domain in _installed:
            continue
        original = compat.get(key)
        if original is None or getattr(original, '_wickedbridge_set', False):
            continue

        def _make(original=original, domain=domain):
            def _wrapped(member, *args, **kwargs):
                # Near-free when nothing is locked: one dict truth test. This
                # runs constantly -- is_sim_allowed_for_sex alone called it
                # twice per invocation, 2586 times in one measured session.
                if _effective:
                    try:
                        _counts['reads'] += 1
                        name = _members(domain).get(member)
                        if name is not None:
                            hit = _effective.get((domain, name))
                            if hit is not None:
                                _counts['overridden'] += 1
                                return hit
                    except Exception:
                        pass
                return original(member, *args, **kwargs)
            _wrapped._wickedbridge_set = True
            return _wrapped

        if compat.rebind(key, _make()):
            _installed.append(domain)
    return list(_installed)


def _lookup(domain):
    entry = _DOMAINS.get(domain)
    if entry is None:
        return None, None
    path, enum_name, getter_name = entry
    module = sys.modules.get(path)
    if module is None:
        return None, None
    return getattr(module, enum_name, None), getattr(module, getter_name, None)


def get(domain, name, default=None):
    """One WickedWhims setting, by domain and member name."""
    enum, getter = _lookup(domain)
    if enum is None or getter is None:
        _misses[domain] = _misses.get(domain, 0) + 1
        return default
    member = getattr(enum, name, None)
    if member is None:
        _misses['%s.%s' % (domain, name)] = _misses.get('%s.%s' % (domain, name), 0) + 1
        return default
    try:
        return getter(member)
    except Exception:
        return default


def sex(name, default=None):
    return get('sex', name, default)


def nudity(name, default=None):
    return get('nudity', name, default)


def relationship(name, default=None):
    return get('relationship', name, default)


def names(domain):
    """Every setting name available in a domain -- useful for discovery."""
    enum, _getter = _lookup(domain)
    if enum is None:
        return []
    return sorted(n for n in dir(enum) if n.isupper())


def report_lines():
    lines = ['settings write: %d/%d domains wrapped'
             % (len(_installed), len(_DOMAINS))]
    for (domain, name), holders in sorted(_locks.items()):
        owners = ', '.join(h[1] for h in holders)
        if (domain, name) in _conflicts:
            lines.append('   CONFLICT %s.%s -- %s disagree, so the player'
                         " setting stands" % (domain, name,
                                              ' vs '.join('%s wants %r' % (o, v)
                                                          for o, v in
                                                          _conflicts[(domain, name)])))
        else:
            lines.append('   locked   %s.%s = %r  by %s'
                         % (domain, name, _effective.get((domain, name)), owners))
    if _effective:
        lines.append('   reads seen=%d overridden=%d'
                     % (_counts['reads'], _counts['overridden']))
    for domain in sorted(_DOMAINS):
        enum, getter = _lookup(domain)
        lines.append('   settings.%-13s available=%s  names=%d'
                     % (domain, enum is not None and getter is not None,
                        len(names(domain))))
    if _misses:
        lines.append('   setting misses: %s' % dict(_misses))
    return lines
