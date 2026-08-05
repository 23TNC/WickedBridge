# -*- coding: utf-8 -*-
"""Satisfaction hooks.

WickedWhims computes satisfaction in one pass when an act ends:

    run_post_sex_satisfaction(instance)
        get_sex_satisfaction_level(sim, instance, target)
            _get_sim_base / _get_sim_dynamic / _get_targets_base / _get_targets_dynamic
        get_sex_satisfaction_buff(sim, instance, is_positive)
        _apply_sex_satisfaction(...)  and  _apply_sex_skill_progression(...)

Two of those are worth substituting rather than merely observing, and both are
proven by traits WickedWhims already ships:

  the LEVEL -- a trait that dulls or sharpens satisfaction changes the number
  the BUFF  -- Exhibitionist swaps WW_SATISFACTION_SEX_CAUGHT (Embarrassed)
               for its _EXHIBITIONIST variant (Happy). Same trigger, opposite
               feeling, chosen by swapping which buff is returned.

So these are resolvers: return a replacement, or None to abstain.
"""

from . import compat, events, satisfaction_model

EV_COMPUTED = 'satisfaction.computed'   # notify  (instance)
EV_LEVEL = 'satisfaction.level'         # resolve (sim, instance, target, ww_value)
EV_PAIR_LEVEL = 'satisfaction.pair_level'
EV_BUFF = 'satisfaction.buff'           # resolve (sim, instance, is_positive, ww_buff)
EV_ALLOWED = 'satisfaction.allowed'     # gate    (instance)

_installed = []
_counts = {'computed': 0, 'level': 0, 'pair_level': 0, 'buff': 0, 'denied': 0}

# PHASE 1: compute the keyed model alongside WickedWhims and compare, but do
# not replace. Flip to True only once the two are shown to agree -- replacing
# it wrongly changes satisfaction for every player with no error to notice.
MODEL_REPLACES_WW = False
_model = {'samples': 0, 'agreed': 0, 'worst_delta': 0.0, 'last': None}


def model_stats():
    return dict(_model)


def _observe_model(args, ww_value):
    """Run the keyed model beside WickedWhims and record how they compare."""
    if len(args) < 3:
        return ww_value
    sim, instance, target = args[0], args[1], args[2]
    try:
        total, breakdown = satisfaction_model.compute(sim, instance, target)
    except Exception:
        return ww_value
    if isinstance(ww_value, (int, float)) and not isinstance(ww_value, bool):
        delta = abs(total - ww_value)
        _model['samples'] += 1
        if delta <= 0.001:
            _model['agreed'] += 1
        if delta > _model['worst_delta']:
            _model['worst_delta'] = delta
        _model['last'] = 'ww=%.3f model=%.3f delta=%.3f  %s' % (
            ww_value, total, delta,
            ', '.join('%s=%.2fx%.2f' % (k, v[0], v[1]) for k, v in sorted(breakdown.items())))
    return total if MODEL_REPLACES_WW else ww_value


def _resolve(event, args, original_value):
    """First non-None answer replaces WickedWhims' value."""
    subs = events.raw_subscribers(event)
    if not subs:
        return original_value
    for sub in subs:
        if sub.muted:
            continue
        try:
            answer = sub.callback(*(args + (original_value,)))
        except Exception:
            events.record_error(sub)
            continue
        if answer is not None:
            _counts[event.split('.', 1)[1]] = _counts.get(event.split('.', 1)[1], 0) + 1
            return answer
    return original_value


def _install_resolver(key, event, value_position=None):
    original = compat.get(key)
    if original is None or getattr(original, '_wickedbridge_res', False):
        return False

    def _wrapped(*args, **kwargs):
        value = original(*args, **kwargs)
        try:
            if event == EV_LEVEL:
                value = _observe_model(args, value)
            return _resolve(event, args, value)
        except Exception:
            return value

    _wrapped._wickedbridge_res = True
    if compat.rebind(key, _wrapped):
        _installed.append(event)
        return True
    return False


def _install_notify(key, event):
    original = compat.get(key)
    if original is None or getattr(original, '_wickedbridge_res', False):
        return False

    def _wrapped(*args, **kwargs):
        result = original(*args, **kwargs)
        try:
            _counts['computed'] += 1
            events.notify(event, *args)
        except Exception:
            pass
        return result

    _wrapped._wickedbridge_res = True
    if compat.rebind(key, _wrapped):
        _installed.append(event)
        return True
    return False


def _install_gate(key, event):
    original = compat.get(key)
    if original is None or getattr(original, '_wickedbridge_res', False):
        return False

    def _wrapped(*args, **kwargs):
        subs = events.raw_subscribers(event)
        if subs:
            for sub in subs:
                if sub.muted:
                    continue
                try:
                    if sub.callback(*args) is False:
                        _counts['denied'] += 1
                        return False
                except Exception:
                    events.record_error(sub)
        return original(*args, **kwargs)

    _wrapped._wickedbridge_res = True
    if compat.rebind(key, _wrapped):
        _installed.append(event)
        return True
    return False


def install():
    """Wrap WickedWhims' satisfaction pipeline. Idempotent."""
    _install_notify('run_post_sex_satisfaction', EV_COMPUTED)
    _install_resolver('get_sex_satisfaction_level', EV_LEVEL)
    _install_resolver('get_sims_sex_satisfaction_level', EV_PAIR_LEVEL)
    _install_resolver('get_sex_satisfaction_buff', EV_BUFF)
    _install_gate('_is_allowed_sex_satisfaction', EV_ALLOWED)
    return list(_installed)


def report_lines():
    lines = ['satisfaction hooks: %d/5' % len(_installed),
             'keyed model: %s, samples=%d agreed=%d worst delta=%.3f'
             % ('REPLACING WW' if MODEL_REPLACES_WW else 'observing only',
                _model['samples'], _model['agreed'], _model['worst_delta'])]
    if _model['last']:
        lines.append('   last: %s' % _model['last'])
    lines += satisfaction_model.report_lines()
    for event in (EV_COMPUTED, EV_LEVEL, EV_PAIR_LEVEL, EV_BUFF, EV_ALLOWED):
        state = 'on' if event in _installed else 'OFF'
        key = event.split('.', 1)[1]
        lines.append('   %-24s %-4s fired/substituted=%d'
                     % (event, state, _counts.get(key, 0)))
    return lines
