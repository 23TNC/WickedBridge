# -*- coding: utf-8 -*-
"""Gating which animations a set of Sims may use.

WickedWhims funnels every animation query through one function:

    get_available_animations(object_identifier, location_constraints, sims_list,
                             additional_tags, additional_no_tags, auto_tags,
                             ignore_animations, filter_fn) -> tuple

It takes the SIMS and returns the ANIMATIONS, and twelve call sites use it --
the start picker, the change picker, the join picker, playlists, autonomy, the
active-sex loader. So one wrapper covers every path by which an animation
becomes available.

This is the surface the gender resolvers were a poor substitute for. Narrowing
a Sim's gender is a per-Sim lever producing a per-animation effect, which is
why it filtered the picker and the slot matcher inconsistently and made anal
behave oddly. Here a subscriber sees the animation itself, and the Sims it
would be used for, and answers about that pair.

Veto-only, like the other gates. Return False to exclude an animation, None to
abstain. There is no way to ADD an animation WickedWhims did not offer -- a
mod cannot conjure animation data, and pretending otherwise would produce
entries that select and then fail.
"""

from . import compat, events

EV_ALLOWED = 'animation.allowed'    # (animation, sims, info) -> False to veto

_installed = []
_counts = {'queries': 0, 'considered': 0, 'vetoed': 0, 'emptied': 0}
_last_veto = [None]


# --------------------------------------------------------------------------
# describing an animation, so a subscriber names no WickedWhims internal
# --------------------------------------------------------------------------
def _call(obj, name, default=None):
    method = getattr(obj, name, None)
    if method is None:
        return default
    try:
        return method()
    except Exception:
        return default


def describe(animation):
    """What a subscriber needs to judge an animation, as plain data.

    Built with getattr so a WickedWhims rename degrades to a missing field
    rather than an exception inside a query the player is waiting on.
    """
    actors = _call(animation, 'get_actors', ()) or ()
    return {
        'id': _call(animation, 'get_animation_id'),
        'identifier': _call(animation, 'get_identifier'),
        'name': _call(animation, 'get_original_string_display_name'),
        'author': _call(animation, 'get_author'),
        'author_id': _call(animation, 'get_author_id'),
        'category': _call(animation, 'get_sex_category'),
        'tags': _call(animation, 'get_tags', ()) or (),
        'actor_count': len(actors),
        'gender_signature': _call(animation, 'get_actors_gender_signature', ()) or (),
        'stage': _call(animation, 'get_stage_name'),
        'is_controversial': _call(animation, 'is_controversial_animation'),
        'allowed_for_random': _call(animation, 'is_allowed_for_random'),
    }


# --------------------------------------------------------------------------
def _filter(animations, sims):
    subs = events.raw_subscribers(EV_ALLOWED)
    if not subs:
        return animations
    kept = []
    for animation in animations:
        _counts['considered'] += 1
        info = None
        vetoed = False
        for sub in subs:
            if sub.muted:
                continue
            try:
                if info is None:
                    # Built once per animation and only when someone is
                    # actually subscribed -- this runs across every animation
                    # in the query, and animation packs run to thousands.
                    info = describe(animation)
                answer = sub.callback(animation, sims, info)
            except Exception:
                events.record_error(sub)
                continue
            if answer is False:
                vetoed = True
                _counts['vetoed'] += 1
                _last_veto[0] = '%s vetoed by %s' % (
                    info.get('name') or info.get('id'),
                    getattr(sub.callback, '__module__', '?'))
                break
        if not vetoed:
            kept.append(animation)
    if animations and not kept:
        # Every animation refused. Legitimate, but it presents to the player
        # as WickedWhims being broken, so it is counted and named.
        _counts['emptied'] += 1
    return tuple(kept)


def install():
    """Wrap get_available_animations. Idempotent."""
    if _installed:
        return list(_installed)
    original = compat.get('get_available_animations')
    if original is None or getattr(original, '_wickedbridge_anim', False):
        return []

    def _wrapped(*args, **kwargs):
        result = original(*args, **kwargs)
        try:
            _counts['queries'] += 1
            if not events.has_subscribers(EV_ALLOWED):
                return result
            # sims_list is the third positional, but callers may pass it by
            # keyword -- take whichever is present rather than assuming.
            sims = kwargs.get('sims_list')
            if sims is None and len(args) >= 3:
                sims = args[2]
            return _filter(result, sims or ())
        except Exception:
            return result

    _wrapped._wickedbridge_anim = True
    if compat.rebind('get_available_animations', _wrapped):
        _installed.append(EV_ALLOWED)
    return list(_installed)


def counts():
    return dict(_counts)


def report_lines():
    lines = ['animation gating: %s' % ('on' if _installed else 'OFF'),
             '   %-22s queries=%d considered=%d vetoed=%d'
             % (EV_ALLOWED, _counts['queries'], _counts['considered'],
                _counts['vetoed'])]
    if _last_veto[0]:
        lines.append('   last veto: %s' % _last_veto[0])
    if _counts['emptied']:
        lines.append('   WARNING %d queries were filtered to ZERO animations -- '
                     'that reads to a player as WickedWhims being broken'
                     % _counts['emptied'])
    if not _installed:
        lines.append('   get_available_animations not resolved -- animation '
                     'gating unavailable')
    return lines
