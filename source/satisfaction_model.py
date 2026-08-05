# -*- coding: utf-8 -*-
"""A keyed, composable model for sex satisfaction.

WickedWhims computes one number per (Sim, partner) pair from four components.
That number composes badly: two mods with opinions about it can only overwrite
each other, and a mod that cares about *being watched* has no way to say so
without also affecting hygiene, mood and everything else.

This replaces the single number with contributions keyed by reason:

    modifiers   {'exposed': 3, 'exhibitionism': 5}    summed per key
    scalers     {'exposed': 0.2}                      averaged per key

    satisfaction = sum over keys of
                       polarity[key] * sum(modifiers[key]) * mean(scalers[key])

A key carries *why*, so two mods can disagree about one reason without touching
any other.

NOTHING A MOD CONTRIBUTES IS EVER NEGATIVE. Modifiers are magnitudes and
scalers are sensitivities; both are rejected below zero. The only sign in the
system is `polarity`, declared once when a key is registered and never
overridable. `exposed` has polarity -1 and `exhibitionism` +1, so a mod
contributing 3 to each is asking for three units of shame and three units of
thrill -- not for a sign flip. Nothing a mod passes in can invert what a key
means, which is what makes contributions from mods that have never heard of
each other safe to combine.

An exhibitionist trait therefore mutes `exposed` with a low scaler and
contributes its own positive `exhibitionism`, which outweighs what remains.

A scaler of 0 MUTES rather than annihilates, because scalers are averaged: one
mod saying 0 alongside another saying 1.0 gives 0.5. Under a product a single 0
would zero the key no matter what anyone else said.

Seeding: WickedWhims' own four component functions are callable individually,
so their returns become the starting values for keys rather than being
recomputed -- that is what stops each reason being counted twice, once inside
WickedWhims and once here. Those returns are signed, so a seed routes by its
sign into whichever of a +/- key pair matches, as a magnitude.

PHASE 1 (this build) is observe-only. The model is computed alongside
WickedWhims' own answer and both are recorded; nothing is replaced. Phase 2
switches over once the two are shown to agree, because getting this wrong
changes satisfaction for everyone with no error to notice.
"""

from . import compat, events

EV_MODIFY = 'satisfaction#modify'
EV_SCALE = 'satisfaction#scale'

# Scalers are SENSITIVITY, never sign -- how much a Sim cares about a reason,
# not whether the reason is good. Sign belongs to the key's polarity.
SCALER_MIN = 0.0
SCALER_MAX = 10.0

# How multiple scalers for one key combine.
#   'mean'    -- arithmetic average. A 0 from one mod MUTES rather than
#                annihilates: mean([0, 1.0]) = 0.5. This is why it is the
#                default -- under a product a single 0 would zero the key
#                outright no matter what any other mod said.
#   'product' -- compounds; one 0 annihilates
#   'geometric' -- middle ground, but still annihilates on a 0
SCALER_COMBINE = 'mean'

# Canonical keys. Mods may register more; unknown keys still work but are
# reported, so a typo is visible rather than silently inert.
_KEYS = {}
_unknown = {}
_rejected = {}


def register_key(name, description='', polarity=1, seeded_from=None,
                 seed_negative_to=None):
    """Declare a satisfaction key.

    polarity          +1 if the key adds to satisfaction, -1 if it subtracts.
                      Mods contribute MAGNITUDES only; the sign is the key own
                      property, declared once here, so no contribution can flip
                      what a key means.
    seeded_from       a WickedWhims component function to take a start value.
    seed_negative_to  where to route the magnitude when a seed comes back
                      negative. The WickedWhims dynamic term is signed, so this
                      sorts it into the matching reason.
    """
    _KEYS[name] = {'description': description,
                   'polarity': 1 if polarity >= 0 else -1,
                   'seeded_from': seeded_from,
                   'seed_negative_to': seed_negative_to}
    return name


def keys():
    return dict(_KEYS)


def _seed_defaults():
    register_key('mood_motives_traits',
                 "the Sim own state: mood, energy, bladder, vampire power, "
                 "Porcelain Doll, Loves Outdoors",
                 polarity=1, seeded_from='_get_sim_base_sex_satisfaction_value',
                 seed_negative_to='mood_motives_penalty')
    register_key('mood_motives_penalty',
                 'the same state when it works against the Sim', polarity=-1)
    # The WickedWhims dynamic term is already signed -- positive when the Sim
    # enjoys being seen, negative otherwise -- so routing by sign sorts its own
    # exhibitionist handling into the right key without double counting it.
    register_key('exhibitionism',
                 'being witnessed, as a reward', polarity=1,
                 seeded_from='_get_sim_dynamic_sex_satisfaction_value',
                 seed_negative_to='exposed')
    register_key('exposed',
                 'being witnessed, as a cost -- jealousy and disapproval',
                 polarity=-1)
    register_key('partner',
                 'partner attributes: attractiveness, penis size against '
                 'preference, hygiene, Slob, friendship and romance',
                 polarity=1, seeded_from='_get_targets_base_sex_satisfaction_value',
                 seed_negative_to='partner_penalty')
    register_key('partner_penalty',
                 'the same attributes when they detract', polarity=-1)
    register_key('lube',
                 'lube level weighted by the vaginal/anal share of the act',
                 polarity=1, seeded_from='_get_targets_dynamic_sex_satisfaction_value',
                 seed_negative_to='friction')
    register_key('friction', 'too little lube for the act', polarity=-1)


_seed_defaults()


def _call(key, *args):
    fn = compat.get(key)
    if fn is None:
        return None
    try:
        return fn(*args)
    except Exception:
        return None


def seed(sim, instance, target):
    """Starting values, taken from WickedWhims' own component functions.

    Those functions return signed numbers -- one component covers both the
    reward and the cost of a reason. Here the sign only chooses WHICH key of a
    +/- pair receives it; the value stored is always a magnitude, so it obeys
    the same rule as anything a mod contributes.
    """
    values = {}
    for name, spec in _KEYS.items():
        source = spec.get('seeded_from')
        if not source:
            continue
        if source.endswith('_dynamic_sex_satisfaction_value') and 'targets' not in source:
            result = _call(source, sim, instance)
        else:
            result = _call(source, sim, instance, target)
        if not isinstance(result, (int, float)) or isinstance(result, bool):
            continue
        key = name
        if result < 0:
            counterpart = spec.get('seed_negative_to')
            if counterpart in _KEYS:
                key = counterpart
            elif spec.get('polarity', 1) > 0:
                # Positive key, negative seed, nowhere to route it: dropping it
                # would silently lose part of WickedWhims' answer, so keep it
                # where it is and record that the key pairing is incomplete.
                _rejected['unrouted_seed'] = _rejected.get('unrouted_seed', 0) + 1
        values[key] = values.get(key, 0) + abs(result)
    return values


def _collect(event, args):
    """Merge every mod's dictionary for this event. Never raises."""
    out = {}
    subs = events.raw_subscribers(event)
    if not subs:
        return out
    for sub in subs:
        if sub.muted:
            continue
        try:
            contribution = sub.callback(*args)
        except Exception:
            events.record_error(sub)
            continue
        if not contribution:
            continue
        try:
            items = contribution.items()
        except AttributeError:
            continue            # a dict is the contract; ignore anything else
        for key, value in items:
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                continue
            # Sign belongs to the key's polarity, so neither a magnitude nor a
            # sensitivity may be negative. Rejecting rather than taking abs()
            # keeps the mistake visible in the status report.
            if value < 0:
                which = 'negative_scaler' if event == EV_SCALE else 'negative_modifier'
                _rejected[which] = _rejected.get(which, 0) + 1
                continue
            if event == EV_SCALE and value > SCALER_MAX:
                _rejected['clamped'] = _rejected.get('clamped', 0) + 1
                value = SCALER_MAX
            if key not in _KEYS:
                _unknown[key] = _unknown.get(key, 0) + 1
            out.setdefault(key, []).append(value)
    return out


def _combine_scalers(values):
    if not values:
        return 1.0
    if SCALER_COMBINE == 'product':
        total = 1.0
        for v in values:
            total *= v
        return total
    if SCALER_COMBINE == 'geometric':
        magnitude = 1.0
        for v in values:
            magnitude *= v
        if magnitude == 0:
            return 0.0
        return magnitude ** (1.0 / len(values))
    return sum(values) / float(len(values))     # 'mean' -- 0 mutes, never annihilates


def compute(sim, instance, target):
    """The keyed model's satisfaction, plus a breakdown for diagnostics."""
    totals = dict(seed(sim, instance, target))
    args = (sim, instance, target)

    for key, values in _collect(EV_MODIFY, args).items():
        totals[key] = totals.get(key, 0) + sum(values)

    scalers = {}
    for key, values in _collect(EV_SCALE, args).items():
        scalers[key] = _combine_scalers(values)

    breakdown = {}
    total = 0
    for key, value in totals.items():
        scaler = scalers.get(key, 1.0)
        # An unregistered key has no declared polarity. Defaulting it to +1
        # rather than guessing means a typo adds rather than subtracts, and
        # unknown_keys() reports it.
        polarity = _KEYS.get(key, {}).get('polarity', 1)
        scaled = polarity * value * scaler
        breakdown[key] = (value, scaler, scaled)
        total += scaled
    return total, breakdown


def unknown_keys():
    return dict(_unknown)


def report_lines():
    lines = ['satisfaction model: %d keys, scalers combined by %s'
             % (len(_KEYS), SCALER_COMBINE)]
    for name in sorted(_KEYS):
        spec = _KEYS[name]
        lines.append('   key %-22s %s  %s'
                     % (name,
                        '+' if spec.get('polarity', 1) > 0 else '-',
                        'seeded' if spec.get('seeded_from') else 'mod-registered'))
    if _unknown:
        lines.append('   UNKNOWN keys used by mods (typos?): %s' % dict(_unknown))
    if _rejected:
        lines.append('   rejected: %s (contributions are magnitudes -- sign '
                     'belongs to the key)' % dict(_rejected))
    return lines
