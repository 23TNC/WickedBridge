# -*- coding: utf-8 -*-
"""Offline harness for WickedBridge.

Stubs the WickedWhims surface that compat.py names, then drives a fake tick
chain the way WickedWhims does. This verifies everything on our side of the
boundary -- installation, dispatch, throttling, identity, isolation -- without
launching the game.

What it cannot verify: that WickedWhims' real SexInstanceTick behaves the way
the stub does. That came from disassembling its bytecode, and only a real
session can confirm it.
"""

import sys, types

PASS, FAIL = [], []


def check(name, condition, detail=''):
    (PASS if condition else FAIL).append(name)
    print('   %-4s %s%s' % ('ok' if condition else 'FAIL', name,
                            ('  -- ' + detail) if detail and not condition else ''))


# --------------------------------------------------------------------------
# stub WickedWhims
# --------------------------------------------------------------------------
def make_module(path):
    module = types.ModuleType(path)
    sys.modules[path] = module
    parts = path.split('.')
    for i in range(1, len(parts)):
        parent = '.'.join(parts[:i])
        if parent not in sys.modules:
            sys.modules[parent] = types.ModuleType(parent)
    return module


class FakeSexInstance(object):
    def __init__(self, ssid, actors):
        self._ssid = ssid
        self._actors = actors

    def get_ssid(self):
        return self._ssid

    def get_actors_list(self):
        return list(self._actors)


class FakeSexInstanceTick(object):
    """Mirrors the contract read out of WickedWhims' bytecode."""

    def __init__(self, is_pose=False):
        self.is_pose = is_pose
        self.tick_handles = []
        self._ticks = 0

    def get_default_tick_handlers(self):
        # 4 handlers for poses, 14 for a full act -- both are plain lists
        return ['stub'] * (4 if self.is_pose else 14)

    def setup_tick_handlers(self):
        self.tick_handles = list(self.get_default_tick_handlers())
        for handler in self.tick_handles:
            if hasattr(handler, 'setup'):
                handler.setup(self)

    def reset_tick_handlers(self, identifiers):
        # WickedWhims reads .identifier off every handler generically
        for handler in tuple(self.tick_handles):
            if getattr(handler, 'identifier', None) in identifiers:
                self.tick_handles.remove(handler)

    def verify_handlers(self):
        for handler in tuple(self.tick_handles):
            if hasattr(handler, '_is_valid') and not handler._is_valid():
                self.tick_handles.remove(handler)

    def update(self, sex_instance):
        # WickedWhims calls _update(ticks, instance) on each handler, not
        # update(instance). Modelling the wrong one hid a live AttributeError.
        self._ticks += 1
        for handler in self.tick_handles:
            if hasattr(handler, '_update'):
                handler._update(self._ticks, sex_instance)


LIVE = []
ZONE_CALLBACKS = []

tick_mod = make_module('wickedwhims.sex.integral.sex_handlers.active_sex'
                       '.active_sex_instance_tick')
tick_mod.SexInstanceTick = FakeSexInstanceTick

handlers_mod = make_module('wickedwhims.sex.integral.sex_handlers.active_sex'
                           '.active_sex_handlers')
handlers_mod.get_active_sex_instances = lambda: list(LIVE)


def register_active_sex_instance(instance):
    LIVE.append(instance)


def unregister_active_sex_instance(instance):
    if instance in LIVE:
        LIVE.remove(instance)


handlers_mod.register_active_sex_instance = register_active_sex_instance
handlers_mod.unregister_active_sex_instance = unregister_active_sex_instance

states_mod = make_module('wickedwhims.sex.integral.sex_handlers.sex_instance_states')
states_mod.SexInstanceStateType = type('SexInstanceStateType', (), {'IS_POSE': 1})

sims_mod = make_module('wickedwhims.sex.generic.utils.sims')
sims_mod.is_sim_allowed_for_sex = lambda sim: True
sims_mod.is_sim_sex_appropriate = lambda sim: True
condoms_mod = make_module('wickedwhims.sex.pregnancy.birth_control.condoms')
condoms_mod.is_condom_applicable_for_sim = lambda sim: True
pills_mod = make_module('wickedwhims.sex.pregnancy.birth_control.pills')
pills_mod.is_birth_control_pill_applicable_for_sim = lambda sim: True
# a caller that imported the predicate before we installed
gate_importer = make_module('wickedwhims.fake_gate_caller')
gate_importer.is_sim_allowed_for_sex = sims_mod.is_sim_allowed_for_sex

zone_mod = make_module('turbolib2.events.zone_spin')


def register_zone_load_event_method(unique_id=None, priority=0, early=False,
                                    late=False, loading_screen=False):
    def _wrap(fn):
        ZONE_CALLBACKS.append(fn)
        return fn
    return _wrap


zone_mod.register_zone_load_event_method = register_zone_load_event_method

# A module that did `from active_sex_handlers import register_active_sex_instance`
# before we installed -- the case that broke the first lifecycle attempt.
importer = make_module('wickedwhims.fake_caller')
importer.register_active_sex_instance = handlers_mod.register_active_sex_instance
importer.unregister_active_sex_instance = handlers_mod.unregister_active_sex_instance

# --------------------------------------------------------------------------
print('--- import and registration ---')
import wickedbridge
from wickedbridge import bootstrap, events, sex

check('module imports', wickedbridge.VERSION == '0.3.0')
check('used turbolib2 zone registration, not the fallback',
      len(ZONE_CALLBACKS) == 1, 'fell back to zone.Zone')

print('--- load-order race ---')
# Simulate our archive importing before WickedWhims: hide the symbols, scan,
# then restore them and confirm zone load recovers.
import wickedbridge.compat as _c
_saved = tick_mod.SexInstanceTick
_saved_reg = handlers_mod.register_active_sex_instance
del tick_mod.SexInstanceTick
del handlers_mod.register_active_sex_instance
_c._scanned = False
_c._resolved.clear()
_c.scan()
check('does not cache a failed scan', not _c._scanned)
check('binding_count is 0 when unresolved, not every module',
      _c.binding_count('register_instance') == 0,
      'got %d' % _c.binding_count('register_instance'))
tick_mod.SexInstanceTick = _saved
handlers_mod.register_active_sex_instance = _saved_reg
_c.scan(force=True)
check('recovers once WickedWhims appears', len(_c.missing(required_only=True)) == 0)

print('--- zone load and install ---')
for cb in ZONE_CALLBACKS:
    cb()
check('all 4 compat symbols resolved', len(bootstrap.compat.missing()) == 0,
      str(bootstrap.compat.missing()))
check('install reported ok', bootstrap._state['install'] == 'ok',
      bootstrap._state['install'])

print('--- handler joins the chain ---')
tick = FakeSexInstanceTick()
tick.setup_tick_handlers()
ours = [h for h in tick.tick_handles if isinstance(h, sex.BridgeTickHandler)]
check('appended to the 14-handler sex chain', len(ours) == 1)
check('appended at the end (runs after WW updates state)',
      isinstance(tick.tick_handles[-1], sex.BridgeTickHandler))

pose = FakeSexInstanceTick(is_pose=True)
pose.setup_tick_handlers()
check('appended to the 4-handler pose chain too',
      any(isinstance(h, sex.BridgeTickHandler) for h in pose.tick_handles))

tick.verify_handlers()
check('survives _verify_handlers (_is_valid returns True)',
      any(isinstance(h, sex.BridgeTickHandler) for h in tick.tick_handles))
probe = sex.BridgeTickHandler()
check('implements _update(ticks, instance) as WW calls it', hasattr(probe, '_update'))
for attr in ('identifier', 'ticks', 'interval'):
    check('mirrors base attribute .%s' % attr, hasattr(probe, attr))
tick.reset_tick_handlers(('some_other_identifier',))
check('survives reset_tick_handlers for other identifiers',
      any(isinstance(h, sex.BridgeTickHandler) for h in tick.tick_handles))

print('--- ticking ---')
act = FakeSexInstance(ssid=1001, actors=['sim_a', 'sim_b'])
handlers_mod.register_active_sex_instance(act)
before = sex._tick_count
for _ in range(10):
    tick.update(act)
check('ticks observed', sex._tick_count - before == 10,
      'got %d' % (sex._tick_count - before))
check('no handler errors', sex._handler_errors == 0)

print('--- handles ---')
handles = sex.active()
check('one active act', len(handles) == 1)
check('actors exposed', handles[0].actors() == ['sim_a', 'sim_b'])
check('handle identity stable across ticks', handles[0].id == sex.active()[0].id)
other = FakeSexInstance(ssid=1001, actors=['sim_c'])   # ssid reuse
handlers_mod.register_active_sex_instance(other)
ids = set(h.id for h in sex.active())
check('ssid reuse does not alias two acts', len(ids) == 2, str(ids))

print('--- events ---')
seen = []
wickedbridge.subscribe('sex.tick', lambda h: seen.append(h.id))
tick.update(act)
check('subscriber received the tick', len(seen) == 1)

throttled = []
wickedbridge.subscribe('sex.tick', lambda h: throttled.append(1), interval=5)
for _ in range(10):
    tick.update(act)
check('interval throttling applied', 0 < len(throttled) < 10,
      'fired %d times in 10 ticks' % len(throttled))

print('--- isolation ---')
def boom(handle):
    raise ValueError('subscriber bug')

wickedbridge.subscribe('sex.tick', boom)
try:
    for _ in range(8):
        tick.update(act)
    survived = True
except Exception:
    survived = False
check('a throwing subscriber never reaches WickedWhims', survived)
check('repeat offender gets muted', events._dispatch_errors >= events.MUTE_AFTER_ERRORS)

print('--- queries ---')
wickedbridge.subscribe('test.q', lambda: None, priority=10)
wickedbridge.subscribe('test.q', lambda: 'answer', priority=5)
check('query: abstain passes through, first definite answer wins',
      events.query('test.q') == 'answer')

print('--- lifecycle ---')
check('lifecycle hooks installed', sex._lifecycle_installed)
check('rebind reached the importing module too, not just the definer',
      importer.register_active_sex_instance is handlers_mod.register_active_sex_instance,
      'importer still holds the original -- wrapper unreachable')
started, stopped, swapped = [], [], []
wickedbridge.subscribe('sex.start', lambda h: started.append(h.id))
wickedbridge.subscribe('sex.stop', lambda h: stopped.append(h.id))
wickedbridge.subscribe('sex.animation_change', lambda h, prev: swapped.append(h.id))

third = FakeSexInstance(ssid=2002, actors=['sim_d', 'sim_e'])
handlers_mod.register_active_sex_instance(third)
check('start fired on registration', len(started) == 1)
check('handle marked running', sex._handle_for(third).running)

class FakeAnimation(object):
    # WickedWhims reuses one object and mutates it -- identity never changes
    def __init__(self): self.ident = 'anim_1'
    def get_identifier(self): return self.ident

shared_anim = FakeAnimation()
FakeSexInstance.get_animation_instance = lambda self: shared_anim
tick.update(third)          # first observation, not a change
tick.update(third)
check('first animation observation is not a change', len(swapped) == 0)
shared_anim.ident = 'anim_2'        # same object, new identifier
tick.update(third)
check('animation swap detected by identifier, not object identity',
      len(swapped) == 1, 'got %d -- identity comparison misses mutation' % len(swapped))

before_seen = len(sex._seen)
handlers_mod.unregister_active_sex_instance(third)
check('stop fired on unregistration', len(stopped) == 1)
check('handle released on stop (no session leak)', len(sex._seen) < before_seen,
      'seen went %d -> %d' % (before_seen, len(sex._seen)))
check('act removed from active list',
      all(h.ssid != 2002 for h in sex.active()))

print('--- gates ---')
from wickedbridge import gates
check('all 4 gates installed', len(gates._installed) == 4, str(gates._installed))
check('gate wrapper reached the importing module too',
      gate_importer.is_sim_allowed_for_sex is sims_mod.is_sim_allowed_for_sex)
check('un-gated predicate still returns WW answer',
      sims_mod.is_sim_allowed_for_sex('sim_x') is True)

denied = {'called': 0}
def deny_chastity(sim):
    denied['called'] += 1
    return False if sim == 'chaste_sim' else None

wickedbridge.gate('sex.allow_sim', deny_chastity)
check('veto denies for the targeted Sim',
      sims_mod.is_sim_allowed_for_sex('chaste_sim') is False)
check('abstain passes through to WickedWhims',
      sims_mod.is_sim_allowed_for_sex('other_sim') is True)
check('veto was attributed', 'deny_chastity' in (gates.veto_log() or ''),
      str(gates.veto_log()))

# veto-only: returning True must not override WickedWhims saying no
sims_mod.is_sim_sex_appropriate = lambda sim: False
condoms_mod._orig = condoms_mod.is_condom_applicable_for_sim
gates._installed.remove('sex.appropriate')
import wickedbridge.compat as _cc
_cc._resolved['is_sim_sex_appropriate'] = sims_mod.is_sim_sex_appropriate
gates.install()
wickedbridge.gate('sex.appropriate', lambda sim: True)
check('returning True does NOT override a WickedWhims refusal',
      sims_mod.is_sim_sex_appropriate('any') is False)

def explode(sim):
    raise RuntimeError('gate bug')
wickedbridge.gate('birthcontrol.pill', explode)
check('a throwing gate falls through to WickedWhims, never raises',
      pills_mod.is_birth_control_pill_applicable_for_sim('sim') is True)

print()
print('%d passed, %d failed' % (len(PASS), len(FAIL)))
if FAIL:
    print('FAILED: %s' % ', '.join(FAIL))
sys.exit(1 if FAIL else 0)
