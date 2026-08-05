# -*- coding: utf-8 -*-
"""Subscription and dispatch.

Two deliberately different kinds of event:

  notify -- fire and forget. Return values ignored, subscriber order is not
            meaningful, exceptions are contained. Many subscribers are fine.

  query  -- has an answer. Subscribers are consulted in priority order and the
            resolution policy is explicit and documented per event, so two mods
            disagreeing produces a defined result rather than a load-order race.

Dispatch runs inside WickedWhims' per-tick handler chain, so nothing here may
raise into the caller. A subscriber that keeps throwing gets muted rather than
being allowed to break sex for the player.
"""

MUTE_AFTER_ERRORS = 5

# name -> list of [priority, callback, interval, offset, errors, muted]
_subs = {}
_dispatch_errors = 0


class _Sub(object):
    __slots__ = ('callback', 'priority', 'interval', 'offset', 'errors', 'muted')

    def __init__(self, callback, priority, interval, offset):
        self.callback = callback
        self.priority = priority
        self.interval = max(1, int(interval))
        self.offset = int(offset)
        self.errors = 0
        self.muted = False

    def due(self, counter):
        if self.interval == 1:
            return True
        return ((counter + self.offset) % self.interval) == 0


def subscribe(event, callback, priority=0, interval=1, offset=0):
    """Register for an event.

    interval/offset throttle high-frequency events: a subscriber asking for
    interval=30 is called every 30th tick, and offset staggers subscribers so
    they do not all land on the same tick.
    """
    subs = _subs.setdefault(event, [])
    sub = _Sub(callback, priority, interval, offset)
    subs.append(sub)
    subs.sort(key=lambda s: -s.priority)
    return sub


def unsubscribe(event, callback):
    subs = _subs.get(event)
    if not subs:
        return False
    for sub in list(subs):
        if sub.callback is callback:
            subs.remove(sub)
            return True
    return False


def subscribers(event):
    """Live subscriber list for an event, priority-ordered."""
    return list(_subs.get(event, ()))


def raw_subscribers(event):
    """The live list itself -- no copy. Hot paths only; do not mutate."""
    return _subs.get(event)


def record_error(sub):
    _record_error(sub)


def has_subscribers(event):
    """Cheap enough to call before building an event payload."""
    subs = _subs.get(event)
    if not subs:
        return False
    for sub in subs:
        if not sub.muted:
            return True
    return False


def _record_error(sub):
    global _dispatch_errors
    _dispatch_errors += 1
    sub.errors += 1
    if sub.errors >= MUTE_AFTER_ERRORS:
        sub.muted = True


def notify(event, *args, **kwargs):
    """Fire and forget. Never raises."""
    subs = _subs.get(event)
    if not subs:
        return 0
    counter = kwargs.pop('_counter', 0)
    delivered = 0
    for sub in list(subs):
        if sub.muted or not sub.due(counter):
            continue
        try:
            sub.callback(*args, **kwargs)
            delivered += 1
        except Exception:
            _record_error(sub)
    return delivered


def query(event, *args, **kwargs):
    """Consult subscribers in priority order; first non-None answer wins.

    Documented policy: highest priority first, first definite answer stops the
    chain. A subscriber returning None abstains.
    """
    subs = _subs.get(event)
    if not subs:
        return None
    for sub in list(subs):
        if sub.muted:
            continue
        try:
            answer = sub.callback(*args, **kwargs)
        except Exception:
            _record_error(sub)
            continue
        if answer is not None:
            return answer
    return None


def report_lines():
    lines = ['dispatch errors: %d' % _dispatch_errors]
    if not _subs:
        lines.append('subscribers: none')
    for event in sorted(_subs):
        subs = _subs[event]
        muted = sum(1 for s in subs if s.muted)
        lines.append('   %-28s subscribers=%d muted=%d' % (event, len(subs), muted))
    return lines
