# -*- coding: utf-8 -*-
"""WickedBridge -- an event layer over WickedWhims.

WickedWhims already ticks. This appends one handler to its sex-instance tick
chain and turns what it observes into events other mods can subscribe to, so
consumers react when WickedWhims does something instead of polling for it.

    import wickedbridge

    def on_tick(sex):
        print(sex.actors())

    wickedbridge.subscribe('sex.tick', on_tick, interval=30)

Design rules, in order of importance:

  1. Only compat.py may name WickedWhims internals. A WickedWhims update
     should be a one-file change.
  2. Nothing here may raise into WickedWhims. We run inside its tick chain;
     a subscriber's bug must not break sex for the player.
  3. Degrade and report. Missing symbols disable a feature and show up in the
     status file -- they never crash a save load.

Status is written to WickedBridge_status.txt in the Sims 4 folder at import
and again at zone load, because a script mod that fails to load is otherwise
completely silent.
"""

from . import bootstrap, compat, events, gates, sex

VERSION = bootstrap.VERSION

# --- subscription ---------------------------------------------------------
subscribe = events.subscribe
unsubscribe = events.unsubscribe

def gate(event, callback, priority=0):
    """Deny something WickedWhims would allow.

    Return False from the callback to deny, None to abstain. Returning True
    does not override WickedWhims' own refusal -- gates are veto-only.
    """
    return events.subscribe(event, callback, priority=priority)


GATES = tuple(g[0] for g in gates.GATES)

# --- queries --------------------------------------------------------------
active = sex.active

# --- diagnostics ----------------------------------------------------------
report = bootstrap.report
write_report = bootstrap.write_report

# Events currently emitted. More arrive as the derived lifecycle lands;
# sex.tick is the primitive the rest are built from.
EVENTS = (
    sex.EV_START,       # (handle)            an act began
    sex.EV_TICK,        # (handle)            once per game tick per active act
    sex.EV_ANIMATION,   # (handle, previous)  the act swapped animation
    sex.EV_STOP,        # (handle)            the act ended
)

bootstrap.start()
