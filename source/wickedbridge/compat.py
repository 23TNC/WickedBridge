# -*- coding: utf-8 -*-
"""Every WickedWhims internal WickedBridge depends on, in one place.

When a WickedWhims update renames something, this is the only file that needs
editing. Nothing else in the package may import from `wickedwhims` or
`turbolib2` directly -- that rule is what makes the bridge maintainable.

Each entry resolves lazily and records whether it was found, so a missing symbol
degrades to a disabled feature and a health warning rather than an exception.
"""

import sys

# --------------------------------------------------------------------------
# module paths
# --------------------------------------------------------------------------
M_TICK = ('wickedwhims.sex.integral.sex_handlers.active_sex'
          '.active_sex_instance_tick')
M_HANDLERS = ('wickedwhims.sex.integral.sex_handlers.active_sex'
              '.active_sex_handlers')
M_INSTANCE = ('wickedwhims.sex.integral.sex_handlers.active_sex'
              '.active_sex_instance')
M_STATES = 'wickedwhims.sex.integral.sex_handlers.sex_instance_states'
M_ZONE = 'turbolib2.events.zone_spin'
M_TICKSVC = 'wickedwhims.main.game_handlers.tick_handler'
M_LOGGER = 'wickedwhims.debug.logger'
M_SIMS = 'wickedwhims.sex.generic.utils.sims'
M_GENDER = 'wickedwhims.sex.enums.sex_gender'
M_CONDOMS = 'wickedwhims.sex.pregnancy.birth_control.condoms'
M_PILLS = 'wickedwhims.sex.pregnancy.birth_control.pills'
M_SATIS = ('wickedwhims.sex.integral.sex_handlers.active_sex.sex_actions'
           '.actions.satisfaction.satisfaction_levels')
M_SATIS_TYPES = ('wickedwhims.sex.integral.sex_handlers.active_sex.sex_actions'
                 '.actions.satisfaction.satisfaction_types')

# What we look up, and why. Order matters only for reporting.
#   key            module      attribute                required?
REQUIRED = (
    ('SexInstanceTick',          M_TICK,     'SexInstanceTick',          True),
    ('get_active_sex_instances', M_HANDLERS, 'get_active_sex_instances', True),
    # Exact start/stop signals. Without these the lifecycle degrades to
    # tick-diffing, which cannot see the end of the last running act.
    ('register_instance',        M_HANDLERS, 'register_active_sex_instance',   False),
    ('unregister_instance',      M_HANDLERS, 'unregister_active_sex_instance', False),
    ('SexInstanceStateType',     M_STATES,   'SexInstanceStateType',     False),
    ('register_zone_load',       M_ZONE,     'register_zone_load_event_method', False),
    ('register_game_update',     M_TICKSVC,  'register_on_game_update_method',  False),
    # gated predicates -- optional, each missing one just disables its gate
    # is_sim_allowed_for_sex was gated here until 0.7.0 -- see gates.GATES for
    # why it was withdrawn. Do not add it back without an enforcement path.
    ('is_sim_sex_appropriate',   M_SIMS,     'is_sim_sex_appropriate',   False),
    # the tuple of animation roles a Sim may fill -- read by the picker,
    # the start test, set_animation_instance and swap_actors
    ('get_sim_sex_genders',      M_GENDER,   'get_sim_sex_genders',      False),
    ('is_condom_applicable_for_sim', M_CONDOMS, 'is_condom_applicable_for_sim', False),
    ('is_birth_control_pill_applicable_for_sim', M_PILLS,
     'is_birth_control_pill_applicable_for_sim', False),
    # satisfaction pipeline -- WickedWhims computes this in one pass on stop
    ('run_post_sex_satisfaction',   M_SATIS, 'run_post_sex_satisfaction',   False),
    ('get_sex_satisfaction_level',  M_SATIS, 'get_sex_satisfaction_level',  False),
    ('get_sims_sex_satisfaction_level', M_SATIS,
     'get_sims_sex_satisfaction_level', False),
    ('_is_allowed_sex_satisfaction', M_SATIS, '_is_allowed_sex_satisfaction', False),
    ('get_sex_satisfaction_buff', M_SATIS_TYPES, 'get_sex_satisfaction_buff', False),
    # component functions the keyed model seeds from -- calling these rather
    # than reimplementing WickedWhims' maths is what avoids double counting
    ('_get_sim_base_sex_satisfaction_value', M_SATIS,
     '_get_sim_base_sex_satisfaction_value', False),
    ('_get_sim_dynamic_sex_satisfaction_value', M_SATIS,
     '_get_sim_dynamic_sex_satisfaction_value', False),
    ('_get_targets_base_sex_satisfaction_value', M_SATIS,
     '_get_targets_base_sex_satisfaction_value', False),
    ('_get_targets_dynamic_sex_satisfaction_value', M_SATIS,
     '_get_targets_dynamic_sex_satisfaction_value', False),
)


def rebind(key, value):
    """Replace a resolved symbol everywhere it is bound.

    WickedWhims uses `from module import name`, so every caller holds its own
    reference. Rebinding only the defining module leaves those callers pointing
    at the original and the wrapper is never reached -- which is exactly how
    the first lifecycle attempt failed silently while the tick handler (a class
    attribute, therefore shared) worked.
    """
    for k, path, attr, _required in REQUIRED:
        if k != key:
            continue
        original = _resolved.get(key)
        rebound = 0
        for module in list(sys.modules.values()):
            if module is None:
                continue
            try:
                if getattr(module, attr, None) is original:
                    setattr(module, attr, value)
                    rebound += 1
            except Exception:
                continue
        if rebound:
            _resolved[key] = value
        return rebound > 0
    return False


def binding_count(key):
    """How many modules currently hold our wrapper for this symbol."""
    for k, path, attr, _required in REQUIRED:
        if k != key:
            continue
        value = _resolved.get(key)
        if value is None:
            return 0          # unresolved: do not count modules lacking the attr
        count = 0
        for module in list(sys.modules.values()):
            if module is None:
                continue
            try:
                if getattr(module, attr, None) is value:
                    count += 1
            except Exception:
                continue
        return count
    return 0

_resolved = {}
_missing = []
_scanned = False


def _module(path):
    return sys.modules.get(path)


def scan(force=False):
    """Resolve symbols. Caches only once everything required is present.

    Script mods import in an order we do not control, so WickedWhims may not be
    loaded yet when this module first runs. Caching an empty result then would
    make the failure permanent -- which is exactly what happened on a run where
    our archive imported first.
    """
    global _scanned
    if _scanned and not force:
        return _resolved
    del _missing[:]
    for key, path, attr, required in REQUIRED:
        module = _module(path)
        value = getattr(module, attr, None) if module is not None else None
        if value is None:
            _missing.append((key, path, attr, required))
        else:
            _resolved[key] = value
    # Only stop rescanning once nothing required is outstanding.
    _scanned = not [m for m in _missing if m[3]]
    return _resolved


def get(key):
    scan()
    return _resolved.get(key)


def missing(required_only=False):
    scan()
    if required_only:
        return [m for m in _missing if m[3]]
    return list(_missing)


def is_wickedwhims_loaded():
    return _module(M_TICK) is not None


def report_lines():
    scan()
    lines = ['WickedWhims loaded: %s' % is_wickedwhims_loaded(),
             'symbols resolved: %d/%d' % (len(_resolved), len(REQUIRED))]
    for key, path, attr, required in _missing:
        lines.append('   MISSING%s %s (%s.%s)'
                     % (' [required]' if required else '', key, path, attr))
    return lines
