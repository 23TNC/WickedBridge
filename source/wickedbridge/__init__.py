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

from . import (bootstrap, compat, events, gates, roles, satisfaction,
               satisfaction_model, settings, sex)

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


def resolve(event, callback, priority=0):
    """Substitute a value WickedWhims would otherwise compute.

    Return a replacement, or None to abstain. Highest priority first, first
    definite answer wins. Reserved for CAS-part and outfit resolution.
    """
    return events.subscribe(event, callback, priority=priority)


def modify(event, callback, priority=0):
    """Contribute amounts, keyed by reason.

        wickedbridge.modify('satisfaction',
                            lambda sim, inst, target: {'exhibitionism': 5,
                                                       'exposed': 3})

    Amounts are MAGNITUDES and must not be negative. Whether a key adds to or
    subtracts from satisfaction is fixed by the key itself -- `exposed` always
    subtracts, `exhibitionism` always adds -- so no mod can invert what another
    mod's key means. Amounts are summed per key.
    """
    return events.subscribe(event + '#modify', callback, priority=priority)


def scale(event, callback, priority=0):
    """Contribute sensitivities, keyed by reason.

        wickedbridge.scale('satisfaction',
                           lambda sim, inst, target: {'exposed': 0.0})

    A scaler says how much this Sim CARES about a reason, never whether the
    reason is good; negatives are rejected. Scalers are averaged per key and
    applied after modifiers are summed, so 0 mutes a key rather than deleting
    it -- that is how an exhibitionist stops minding being seen while still
    earning from `exhibitionism`.
    """
    return events.subscribe(event + '#scale', callback, priority=priority)


# Role helpers, so a subscriber to sex.sim_genders never needs a SexGenderType
# constant of its own.
without_male_roles = roles.without_male_roles
is_male_role = roles.is_male
is_female_role = roles.is_female
opposite_role = roles.opposite

# The satisfaction keys mods may contribute to, and how to add more.
satisfaction_keys = satisfaction_model.keys
register_satisfaction_key = satisfaction_model.register_key

GATES = tuple(g[0] for g in gates.GATES) + (satisfaction.EV_ALLOWED,)

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
    sex.EV_AFTER_STOP,  # (handle)            a timer, N ticks after stop
    satisfaction.EV_COMPUTED,   # (instance)  WickedWhims finished its
                                #             post-sex satisfaction pass
)

# Resolvers -- return a replacement, or None to abstain. The last argument is
# always WickedWhims' own value, so a subscriber can scale rather than replace.
RESOLVERS = (
    roles.EV_SIM_GENDERS,        # (turbo_sim, *args, ww_genders) -> tuple
    satisfaction.EV_LEVEL,       # (sim, instance, target, ww_level)
    satisfaction.EV_PAIR_LEVEL,  # (sim, target, instance, ww_level)
    satisfaction.EV_BUFF,        # (sim, instance, is_positive, ww_buff)
)

bootstrap.start()
