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
EV_SIM_GENDER = 'sex.sim_gender'     # (turbo_sim, *args, ww_gender)  -> gender

_installed = []
_counts = {'calls': 0, 'narrowed': 0, 'refused_empty': 0,
           'no_female_role': 0, 'native_calls': 0, 'native_narrowed': 0}
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


# --------------------------------------------------------------------------
# helpers for subscribers, so no consumer has to name a SexGenderType constant
# --------------------------------------------------------------------------
def is_male(gender):
    fn = compat.get('is_male_sex_gender')
    return bool(fn(gender)) if fn is not None else False


def is_female(gender):
    fn = compat.get('is_female_sex_gender')
    return bool(fn(gender)) if fn is not None else False


def opposite(gender):
    fn = compat.get('opposite_sex_gender')
    return fn(gender) if fn is not None else gender


def without_male_role(gender):
    """One gender, mapped off a penis-requiring role. Constant-free."""
    return opposite(gender) if is_male(gender) else gender


def without_male_roles(genders):
    """The same Sim, admitted only to roles that do not require a penis.

    Written without a single SexGenderType constant -- every decision goes
    through WickedWhims' own predicates, because the occult variants are
    numerous and a mistyped one would quietly admit a Sim to the role a mod
    meant to deny.

    Removing rather than replacing is tried first: a Sim who already has a
    female role keeps it untouched, occult and all. Only when nothing survives
    is the male role mapped to its opposite, which is what makes this work for
    a Sim who is male-only -- returning nothing at all would read to
    WickedWhims as a broken Sim, not a restricted one.

    Returns the input unchanged if neither step leaves anything, so a caller
    can tell "no change was possible" from "no change was wanted".
    """
    genders = tuple(genders)
    kept = tuple(g for g in genders if not is_male(g))
    if kept:
        return kept
    mapped = []
    for gender in genders:
        flipped = opposite(gender)
        if not is_male(flipped) and flipped not in mapped:
            mapped.append(flipped)
    if mapped:
        return tuple(mapped)
    _counts['no_female_role'] += 1
    return genders


def _resolve_single(args, original):
    """First definite answer wins, then chains, same shape as _resolve."""
    subs = events.raw_subscribers(EV_SIM_GENDER)
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
        if answer is not None:
            value = answer
    if value != original:
        _counts['native_narrowed'] += 1
        _last[0] = '%s -> %s (native)' % (original, value)
    return value


def install():
    """Wrap both gender functions. Idempotent.

    Both are needed and they are not redundant. get_sim_sex_genders feeds the
    picker and the start test; get_sim_native_sex_gender feeds those AND the
    (gender, allow_any) pairs set_animation_instance matches against animation
    slots. Wrapping only the first filtered which animations were offered while
    leaving actor-to-slot assignment on the unnarrowed value -- a caged Sim
    still took the male role in an animation that had been allowed through.
    """
    for key, event, resolver in (
            ('get_sim_native_sex_gender', EV_SIM_GENDER, _resolve_single),
            ('get_sim_sex_genders', EV_SIM_GENDERS, _resolve)):
        if event in _installed:
            continue
        original = compat.get(key)
        if original is None or getattr(original, '_wickedbridge_roles', False):
            continue

        def _make(original=original, resolver=resolver, event=event):
            counter = 'native_calls' if event == EV_SIM_GENDER else 'calls'

            def _wrapped(*args, **kwargs):
                result = original(*args, **kwargs)
                try:
                    _counts[counter] += 1
                    return resolver(args, result)
                except Exception:
                    return result
            _wrapped._wickedbridge_roles = True
            return _wrapped

        if compat.rebind(key, _make()):
            _installed.append(event)
    return list(_installed)


def counts():
    return dict(_counts)


def report_lines():
    lines = ['role resolution: %d/2 hooks' % len(_installed),
             '   %-24s calls=%d narrowed=%d   (slot assignment)'
             % (EV_SIM_GENDER, _counts['native_calls'], _counts['native_narrowed']),
             '   %-24s calls=%d narrowed=%d   (picker and start test)'
             % (EV_SIM_GENDERS, _counts['calls'], _counts['narrowed'])]
    if EV_SIM_GENDER not in _installed:
        lines.append('   WARNING sex.sim_gender is OFF -- narrowing will filter '
                     'the picker but not which Sim takes which slot')
    if _last[0]:
        lines.append('   last narrowing: %s' % _last[0])
    if _counts['no_female_role']:
        lines.append('   %d Sims had no non-male role to fall back on -- left '
                     'unchanged' % _counts['no_female_role'])
    if _counts['refused_empty']:
        lines.append('   refused %d empty replacements (a Sim must fit some '
                     'role)' % _counts['refused_empty'])
    return lines
