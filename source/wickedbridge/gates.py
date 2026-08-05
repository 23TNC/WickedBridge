# -*- coding: utf-8 -*-
"""Gates -- letting mods deny things WickedWhims would otherwise allow.

A gate wraps a WickedWhims predicate. Subscribers may return False to deny, or
None to abstain. Returning True does NOT force a yes: if WickedWhims itself
says no, that stands. Gates are veto-only by design, so the bridge can never
become a way around WickedWhims' own age, incest or consent rules.

Every veto is attributed. "Sex stopped working" is otherwise unattributable and
lands on WickedWhims' bug tracker instead of the mod that caused it.
"""

from . import compat, events

# gate event -> (compat key, human description)
# event, compat key, cadence, description.
#
# Cadence is measured, not guessed -- one live session of two acts gave
# sex.allow_sim 2586 calls and birthcontrol.condom 46. Keep callbacks on a HOT
# gate cheap: no relationship walks, no tuning lookups.
GATES = (
    ('sex.allow_sim',       'is_sim_allowed_for_sex',       'HOT ~1/tick/Sim',
     'may this Sim take part in sex at all'),
    ('sex.appropriate',     'is_sim_sex_appropriate',       'HOT ~1/tick/Sim',
     'is sex contextually appropriate for this Sim'),
    ('birthcontrol.condom', 'is_condom_applicable_for_sim', 'per act',
     'may this Sim use a condom'),
    ('birthcontrol.pill',   'is_birth_control_pill_applicable_for_sim', 'per act',
     'may this Sim use birth control pills'),
)

_installed = []
_vetoes = {}            # gate event -> count
_last_veto = [None]     # (event, subscriber description)


def veto_log():
    return _last_veto[0]


def _describe(callback):
    module = getattr(callback, '__module__', '?')
    name = getattr(callback, '__name__', repr(callback))
    return '%s.%s' % (module, name)


def _run_gate(event, args):
    """True if a subscriber denied. Records who, for attribution."""
    # Live list, not a copy: these run per tick per Sim and allocating on every
    # call is measurable at that rate. Subscribers are not removed mid-dispatch.
    subs = events.raw_subscribers(event)
    if not subs:
        return False
    for sub in subs:
        if sub.muted:
            continue
        try:
            answer = sub.callback(*args)
        except Exception:
            events.record_error(sub)
            continue
        if answer is False:
            _vetoes[event] = _vetoes.get(event, 0) + 1
            _last_veto[0] = '%s denied by %s' % (event, _describe(sub.callback))
            return True
    return False


def install():
    """Wrap each WickedWhims predicate we gate. Idempotent."""
    for event, key, _cadence, _description in GATES:
        if event in _installed:
            continue
        original = compat.get(key)
        if original is None or getattr(original, '_wickedbridge_gate', False):
            continue

        def _make(original=original, event=event):
            def _wrapped(*args, **kwargs):
                try:
                    if _run_gate(event, args):
                        return False
                except Exception:
                    pass
                return original(*args, **kwargs)
            _wrapped._wickedbridge_gate = True
            return _wrapped

        if compat.rebind(key, _make()):
            _installed.append(event)
    return list(_installed)


def report_lines():
    lines = ['gates installed: %d/%d' % (len(_installed), len(GATES))]
    for event, key, cadence, description in GATES:
        state = 'on' if event in _installed else 'OFF'
        lines.append('   %-22s %-4s %-17s vetoes=%d  (%s)'
                     % (event, state, cadence, _vetoes.get(event, 0), description))
    if _last_veto[0]:
        lines.append('   last veto: %s' % _last_veto[0])
    return lines
