# -*- coding: utf-8 -*-
"""HelloWickedBridge -- the smallest possible WickedBridge consumer.

Appends a line to WickedBridge_hello.txt whenever a sex act starts or stops.
It exists to demonstrate the API and to prove the whole chain works in a real
session: if this file gets written, WickedBridge installed into WickedWhims'
tick chain and dispatched to a subscriber in a separate mod.

The entire integration is the three subscribe() calls at the bottom. There is
no injection, no WickedWhims import, and no polling -- this runs only when
WickedWhims does something.
"""

import os

LOG_NAME = 'WickedBridge_hello.txt'


def _log_path():
    base = 'C:' + os.sep + os.path.join('Users', 'Wolf', 'Documents',
                                        'Electronic Arts', 'The Sims 4')
    candidates = [os.path.join(base, LOG_NAME)]
    try:
        home = os.path.expanduser('~')
        candidates.append(os.path.join(home, 'Documents', 'Electronic Arts',
                                       'The Sims 4', LOG_NAME))
    except Exception:
        pass
    return candidates


def _write(message):
    for path in _log_path():
        try:
            with open(path, 'a') as handle:
                handle.write(message)
                handle.write(chr(10))
            return True
        except Exception:
            continue
    return False


def on_sex_start(sex):
    _write('hello -- act %s started with %d actors'
           % (sex.id, len(sex.actors())))


def on_sex_stop(sex):
    _write('goodbye -- act %s ended after %d ticks' % (sex.id, sex.ticks))
    _write('   gate calls so far: %s' % gate_summary())


def on_animation_change(sex, previous):
    _write('   act %s changed animation (was %r)' % (sex.id, previous))


def on_sex_tick(sex):
    # interval=100 so this stays quiet; proves throttling works in a real session
    _write('   ...act %s still running at tick %d' % (sex.id, sex.ticks))


# --------------------------------------------------------------------------
# Gate observation.
#
# These abstain -- they return None and change nothing. They exist to answer a
# question the offline tests cannot: does WickedWhims actually consult these
# predicates during real play, and on which paths? Each logs its first few
# calls, then goes quiet so it does not flood the file.
# --------------------------------------------------------------------------
_gate_calls = {}


def _observer(gate_name):
    def _observe(*args):
        count = _gate_calls.get(gate_name, 0) + 1
        _gate_calls[gate_name] = count
        if count <= 3:
            _write('   gate %s consulted (call %d, %d args)'
                   % (gate_name, count, len(args)))
        return None          # abstain: WickedWhims' own answer stands
    return _observe


def gate_summary():
    return ', '.join('%s=%d' % (k, v) for k, v in sorted(_gate_calls.items())) or 'none consulted'


try:
    import wickedbridge

    wickedbridge.subscribe('sex.start', on_sex_start)
    wickedbridge.subscribe('sex.stop', on_sex_stop)
    wickedbridge.subscribe('sex.animation_change', on_animation_change)
    wickedbridge.subscribe('sex.tick', on_sex_tick, interval=100)
    for _name in wickedbridge.GATES:
        wickedbridge.gate(_name, _observer(_name))

    # A worked exhibitionism example, showing why nothing here is negative.
    # This Sim stops minding being seen (scaler 0 on `exposed`, whose polarity
    # is already -1) and gains from being seen instead (a positive amount on
    # `exhibitionism`, polarity +1). Another mod can raise `exposed` for its
    # own reasons and the two compose -- neither can flip the other's meaning,
    # because sign lives in the key and not in what we pass.
    wickedbridge.scale('satisfaction', lambda sim, inst, target: {'exposed': 0.0})
    wickedbridge.modify('satisfaction', lambda sim, inst, target: {'exhibitionism': 4})
    _write('HelloWickedBridge subscribed (bridge %s), observing gates: %s'
           % (wickedbridge.VERSION, ', '.join(wickedbridge.GATES)))
except Exception as ex:
    _write('HelloWickedBridge could not reach WickedBridge: %r' % (ex,))
