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

_DOMAINS = {
    'sex': ('wickedwhims.sex.sex_settings', 'SexSetting', 'get_sex_setting'),
    'nudity': ('wickedwhims.nudity.nudity_settings', 'NuditySetting',
               'get_nudity_setting'),
    'relationship': ('wickedwhims.relationships.relationship_settings',
                     'RelationshipSetting', 'get_relationship_setting'),
}

_misses = {}


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
    lines = []
    for domain in sorted(_DOMAINS):
        enum, getter = _lookup(domain)
        lines.append('   settings.%-13s available=%s  names=%d'
                     % (domain, enum is not None and getter is not None,
                        len(names(domain))))
    if _misses:
        lines.append('   setting misses: %s' % dict(_misses))
    return lines
