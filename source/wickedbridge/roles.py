# -*- coding: utf-8 -*-
"""Which animation roles a Sim may fill.

Every WickedWhims animation has ordered actor slots, and each slot declares a
`gender_type`. A Sim is admitted to a slot by comparing that against the Sim's
own sex genders, which WickedWhims resolves in `get_sim_sex_genders`:

    get_sim_native_sex_gender   setting SEX_BASED -> CAS gender
                                else WW_GENDER_RECOGNITION statistic
                                else has_sim_penis()
    get_sim_occult_sex_gender   maps that onto VAMPIRE_MALE, FAIRY_FEMALE, ...
    get_sim_sex_genders         returns a TUPLE, and appends the opposite
                                variant when WW_GENDER_RECOGNITION_ALLOW_ANY

That tuple is the single value everything downstream reads:

    open_start_sex_sims_picker_dialog        what the picker offers
    _cacheable_test_for_sex_start            whether the interaction appears
    set_animation_instance                   -> is_matching_sims_genders
    swap_actors                              -> is_fitting_gender_type

So narrowing the tuple narrows the roles, everywhere, in one place. This is a
RESOLVER rather than a gate on purpose: `sex.allow_sim` taught us that a
predicate which merely answers is not the same as one that decides. This value
is consumed by the code that actually assigns Sims to slots.

Subscribers return a replacement tuple, or None to abstain. Returning an empty
tuple would make a Sim fit nothing at all, which reads to WickedWhims as a
broken Sim rather than a restricted one, so it is refused.
"""

from . import compat, events

EV_SIM_GENDERS = 'sex.sim_genders'   # (turbo_sim, *args, ww_genders) -> tuple

_installed = []
_counts = {'calls': 0, 'narrowed': 0, 'refused_empty': 0}
_last = [None]


def _resolve(args, original):
    subs = events.raw_subscribers(EV_SIM_GENDERS)
    if not subs:
        return original
    value = original
    for sub in subs:
        if sub.muted:
            continue
        try:
            answer = sub.callback(*(tuple(args) + (value,)))
        except Exception:
            events.record_error(sub)
            continue
        if answer is None:
            continue
        try:
            answer = tuple(answer)
        except TypeError:
            continue
        if not answer:
            # A Sim that fits no role at all is not "restricted", it is broken:
            # WickedWhims would drop them from pickers with no explanation and
            # no way to tell this apart from a bug in its own gender code.
            _counts['refused_empty'] += 1
            continue
        value = answer          # chained, so two mods can each narrow it
    if value != original:
        _counts['narrowed'] += 1
        _last[0] = '%s -> %s' % (original, value)
    return value


def install():
    """Wrap get_sim_sex_genders. Idempotent."""
    if _installed:
        return list(_installed)
    original = compat.get('get_sim_sex_genders')
    if original is None or getattr(original, '_wickedbridge_roles', False):
        return []

    def _wrapped(*args, **kwargs):
        result = original(*args, **kwargs)
        try:
            _counts['calls'] += 1
            return _resolve(args, result)
        except Exception:
            return result

    _wrapped._wickedbridge_roles = True
    if compat.rebind('get_sim_sex_genders', _wrapped):
        _installed.append(EV_SIM_GENDERS)
    return list(_installed)


def counts():
    return dict(_counts)


def report_lines():
    lines = ['role resolution: %s' % ('on' if _installed else 'OFF'),
             '   %-24s calls=%d narrowed=%d'
             % (EV_SIM_GENDERS, _counts['calls'], _counts['narrowed'])]
    if _last[0]:
        lines.append('   last narrowing: %s' % _last[0])
    if _counts['refused_empty']:
        lines.append('   refused %d empty replacements (a Sim must fit some '
                     'role)' % _counts['refused_empty'])
    return lines
