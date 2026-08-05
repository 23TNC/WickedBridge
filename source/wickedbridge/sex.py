# -*- coding: utf-8 -*-
"""The tick handler, and the sex-instance handles handed to subscribers.

WickedWhims already ticks: SexInstanceTick walks a chain of handlers once per
game tick per active sex instance. We append one handler to that chain, so we
are called by WickedWhims rather than running any loop of our own. No active
sex means no calls at all.

Handler contract, verified against WickedWhims' own implementation:

    _update(ticks, instance)          the method SexInstanceTick calls on every
                                      entry in tick_handles -- NOT update()
    insert_tick_handler(cls, index)   instantiates cls() with no arguments,
                                      inserts it, then calls setup(instance)
    _verify_handlers()                drops any handler whose _is_valid() is
                                      false -- so ours must return True or it
                                      is silently evicted mid-act
    get_default_tick_handlers()       returns 4 handlers for poses, 14 for a
                                      full sex act, so we must tolerate both
"""

from . import compat, events

EV_TICK = 'sex.tick'
EV_START = 'sex.start'
EV_STOP = 'sex.stop'
EV_ANIMATION = 'sex.animation_change'
# A timer, N ticks after stop. NOT WickedWhims' post-sex processing --
# that is satisfaction.computed, in satisfaction.py.
EV_AFTER_STOP = 'sex.after_stop'

_installed = False
_lifecycle_installed = False
_tick_count = 0
_handler_errors = 0
_seen = {}          # (id(instance), ssid) -> _SexHandle
_next_handle = [1]
_counts = {'start': 0, 'stop': 0, 'animation': 0, 'acts': 0, 'after_stop': 0}
AFTER_STOP_DELAY_TICKS = 30
_pending_after = []          # [[handle, ticks_remaining], ...]
_last = {'animation_id': None}


class _SexHandle(object):
    """Stable identity for one sex act.

    Keyed on the instance object plus its ssid rather than ssid alone, so that
    if WickedWhims ever recycles an ssid a subscriber's state does not silently
    alias onto a different act.
    """

    __slots__ = ('id', 'ssid', '_instance', 'ticks', 'running', '_animation')

    def __init__(self, handle_id, ssid, instance):
        self.id = handle_id
        self.ssid = ssid
        self._instance = instance
        self.ticks = 0
        self.running = True
        self._animation = None

    def _call(self, *names):
        """First of `names` that exists and returns without raising."""
        for name in names:
            getter = getattr(self._instance, name, None)
            if not callable(getter):
                continue
            try:
                return getter()
            except Exception:
                continue
        return None

    def animation(self):
        """The current animation instance, or None."""
        return self._call('get_animation_instance')

    def animation_id(self):
        """Identity of the current animation.

        WickedWhims reuses the same SexAnimationInstance object and mutates it
        when the animation changes, so comparing object identity never detects a
        swap. The identifier does.
        """
        animation = self.animation()
        if animation is None:
            return None
        for name in ('get_identifier', 'get_animation_id', 'get_display_name'):
            getter = getattr(animation, name, None)
            if not callable(getter):
                continue
            try:
                value = getter()
            except Exception:
                continue
            if value is not None:
                return value
        return id(animation)

    def categories(self):
        """Sex categories counted so far in this act, as WickedWhims reports them."""
        animation = self.animation()
        if animation is None:
            return []
        getter = getattr(animation, 'get_sex_category', None)
        if not callable(getter):
            return []
        try:
            category = getter()
        except Exception:
            return []
        return [] if category is None else [category]

    def actor_count(self):
        count = self._call('get_actors_count')
        return count if isinstance(count, int) else len(self.actors())

    def actors(self):
        for name in ('get_actors_as_turbo_sim', 'get_actors_list'):
            getter = getattr(self._instance, name, None)
            if not callable(getter):
                continue
            try:
                actors = getter()
                if actors:
                    return list(actors)
            except Exception:
                continue
        return []

    def cancel(self, reason='WickedBridge'):
        """Ask WickedWhims to end this act. True if a call was accepted."""
        for name, kwargs in (('cancel', {'reason': reason}),
                             ('stop', {'hard_stop': True, 'stop_reason': reason})):
            method = getattr(self._instance, name, None)
            if not callable(method):
                continue
            try:
                method(**kwargs)
                return True
            except TypeError:
                try:
                    method()
                    return True
                except Exception:
                    continue
            except Exception:
                continue
        return False

    def raw(self):
        """The underlying WickedWhims instance, for callers that need more than
        the bridge exposes. Using this reintroduces the coupling the bridge
        exists to remove -- prefer asking for an accessor."""
        return self._instance

    def __repr__(self):
        return '<SexHandle id=%s ssid=%s ticks=%d>' % (self.id, self.ssid, self.ticks)


def _ssid_of(instance):
    getter = getattr(instance, 'get_ssid', None)
    if callable(getter):
        try:
            return getter()
        except Exception:
            return None
    return None


def _handle_for(instance):
    ssid = _ssid_of(instance)
    key = (id(instance), ssid)
    handle = _seen.get(key)
    if handle is None:
        handle = _SexHandle(_next_handle[0], ssid, instance)
        _next_handle[0] += 1
        _counts['acts'] += 1
        _seen[key] = handle
    return handle


class BridgeTickHandler(object):
    """Appended to WickedWhims' tick chain. Step one does nothing but count."""

    # Mirrors every attribute WickedWhims' _SexInstanceTickTracker.__init__
    # sets, because its machinery reads them off handlers generically:
    #   identifier -- read by SexInstanceTick.reset_tick_handlers
    #   ticks      -- read and written by the base _update
    #   interval   -- read by the base _update
    # A unique identifier string means WickedWhims' targeted resets never
    # match us, which is what we want.
    def __init__(self):
        self.identifier = 'wickedbridge'
        self.ticks = 0
        self.interval = 1

    def setup(self, sex_instance):
        return None

    def reset(self, sex_instance):
        return None

    def _is_valid(self):
        # Returning False here would have WickedWhims silently remove us.
        return True

    def _update(self, ticks, sex_instance):
        """The method SexInstanceTick actually calls on each handler.

        WickedWhims' _SexInstanceTickTracker exposes _update(ticks, instance) as
        the framework entry point and update(instance) as the overridable. Only
        implementing update() raises AttributeError inside WW's tick loop.
        """
        return self.update(sex_instance)

    def update(self, sex_instance):
        global _tick_count, _handler_errors
        try:
            _tick_count += 1
            handle = _handle_for(sex_instance)
            handle.ticks += 1
            _check_animation(handle)
            if events.has_subscribers(EV_TICK):
                events.notify(EV_TICK, handle, _counter=handle.ticks)
        except Exception:
            _handler_errors += 1
        return None


def _check_animation(handle):
    """Emit animation_change when the instance swaps animation mid-act."""
    current = handle.animation_id()
    previous = handle._animation
    if current == previous:
        return
    handle._animation = current
    _last['animation_id'] = current
    if previous is None:
        return          # first observation is the start, not a change
    _counts['animation'] += 1
    events.notify(EV_ANIMATION, handle, previous)


def _on_register(instance):
    handle = _handle_for(instance)
    handle.running = True
    _counts['start'] += 1
    events.notify(EV_START, handle)
    _refresh_status()


def _on_unregister(instance):
    handle = _handle_for(instance)
    handle.running = False
    _counts['stop'] += 1
    events.notify(EV_STOP, handle)
    if events.has_subscribers(EV_AFTER_STOP):
        _pending_after.append([handle, AFTER_STOP_DELAY_TICKS])
    # Release the handle now the act is over; without this _seen grows for the
    # whole session.
    _seen.pop((id(instance), _ssid_of(instance)), None)
    _refresh_status()


def _drain_pending_after(ticks=1, *args, **kwargs):
    """Fire sex.post_sex once its delay elapses.

    Driven by the game update, not the tick chain: no handler ticks for an act
    once it has ended, so a tick-driven delay could never fire for the last
    running act.
    """
    if not _pending_after:
        return
    step = ticks if isinstance(ticks, int) else 1
    for entry in list(_pending_after):
        entry[1] -= step
        if entry[1] > 0:
            continue
        _pending_after.remove(entry)
        _counts['after_stop'] += 1
        events.notify(EV_AFTER_STOP, entry[0])


def install_after_stop():
    """Drive the post-sex delay off WickedWhims' game update."""
    register = compat.get('register_game_update')
    if register is None:
        return False
    for attempt in (lambda: register(unique_id='wickedbridge_after_stop')(_drain_pending_after),
                    lambda: register(_drain_pending_after)):
        try:
            attempt()
            return True
        except Exception:
            continue
    return False


def _refresh_status():
    """Rewrite the status file on rare events so it is not a zone-load snapshot."""
    try:
        from . import bootstrap
        bootstrap.write_report()
    except Exception:
        pass


def install_lifecycle():
    """Wrap WickedWhims' instance registry for exact start/stop events.

    Preferred over diffing live instances each tick: our tick handler only runs
    while an act is in progress, so a tick-diff cannot observe the end of the
    last running act.
    """
    global _lifecycle_installed
    if _lifecycle_installed:
        return True
    installed = 0
    for key, callback in (('register_instance', _on_register),
                          ('unregister_instance', _on_unregister)):
        original = compat.get(key)
        if original is None or getattr(original, '_wickedbridge', False):
            continue

        def _make(original=original, callback=callback):
            def _wrapped(instance, *args, **kwargs):
                result = original(instance, *args, **kwargs)
                try:
                    callback(instance)
                except Exception:
                    pass
                return result
            _wrapped._wickedbridge = True
            return _wrapped

        if compat.rebind(key, _make()):
            installed += 1
    _lifecycle_installed = installed > 0
    return _lifecycle_installed


def install():
    """Append our handler to whichever chain WickedWhims builds."""
    global _installed
    if _installed:
        return True
    tick_class = compat.get('SexInstanceTick')
    if tick_class is None:
        return False
    original = getattr(tick_class, 'get_default_tick_handlers', None)
    if original is None:
        return False
    if getattr(original, '_wickedbridge', False):
        _installed = True
        return True

    def _get_default_tick_handlers(self):
        handlers = original(self)
        try:
            if handlers is not None:
                handlers.append(BridgeTickHandler())
        except Exception:
            pass
        return handlers

    _get_default_tick_handlers._wickedbridge = True
    try:
        tick_class.get_default_tick_handlers = _get_default_tick_handlers
    except Exception:
        return False
    _installed = True
    return True


def active():
    """Every sex act WickedWhims currently has running."""
    getter = compat.get('get_active_sex_instances')
    if getter is None:
        return []
    try:
        return [_handle_for(i) for i in (getter() or ())]
    except Exception:
        return []


def report_lines():
    return ['tick handler installed: %s' % _installed,
            'lifecycle hooks installed: %s' % _lifecycle_installed,
            'lifecycle bindings captured: register=%d unregister=%d'
            % (compat.binding_count('register_instance'),
               compat.binding_count('unregister_instance')),
            'last animation id seen: %r' % (_last['animation_id'],),
            'acts started: %d  stopped: %d  animation changes: %d  after_stop: %d'
            % (_counts['start'], _counts['stop'], _counts['animation'], _counts['after_stop']),
            'ticks observed: %d' % _tick_count,
            'handler errors: %d' % _handler_errors,
            'acts seen this session: %d  (live handles: %d, awaiting after_stop: %d)'
            % (_counts['acts'], len(_seen), len(_pending_after)),
            'acts running now: %d' % len(active())]
