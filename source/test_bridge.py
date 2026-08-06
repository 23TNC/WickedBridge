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
sims_mod.is_sim_allowed_for_sex = lambda sim: True   # still defined by WW; no longer gated
sims_mod.is_sim_sex_appropriate = lambda sim: True
condoms_mod = make_module('wickedwhims.sex.pregnancy.birth_control.condoms')
condoms_mod.is_condom_applicable_for_sim = lambda sim: True
pills_mod = make_module('wickedwhims.sex.pregnancy.birth_control.pills')
pills_mod.is_birth_control_pill_applicable_for_sim = lambda sim: True
# a caller that imported the predicate before we installed
gate_importer = make_module('wickedwhims.fake_gate_caller')
gate_importer.is_sim_sex_appropriate = sims_mod.is_sim_sex_appropriate

GAME_UPDATE = []
ticksvc_mod = make_module('wickedwhims.main.game_handlers.tick_handler')
def register_on_game_update_method(unique_id=None, interval=None):
    def _wrap(fn):
        GAME_UPDATE.append(fn); return fn
    return _wrap
ticksvc_mod.register_on_game_update_method = register_on_game_update_method

setsex_mod = make_module('wickedwhims.sex.sex_settings')
setsex_mod.SexSetting = type('SexSetting', (), {'CUM_SWITCH_STATE': 'k1'})
setsex_mod.get_sex_setting = lambda member: 'ON' if member == 'k1' else None

SATIS = ('wickedwhims.sex.integral.sex_handlers.active_sex.sex_actions'
         '.actions.satisfaction.satisfaction_levels')
STYPES = ('wickedwhims.sex.integral.sex_handlers.active_sex.sex_actions'
          '.actions.satisfaction.satisfaction_types')
satis_mod = make_module(SATIS)
satis_mod.run_post_sex_satisfaction = lambda instance: 'done'
satis_mod.get_sex_satisfaction_level = lambda sim, instance, target: 10
satis_mod.get_sims_sex_satisfaction_level = lambda sim, target, instance: 20
satis_mod._is_allowed_sex_satisfaction = lambda instance: True
stypes_mod = make_module(STYPES)
stypes_mod.get_sex_satisfaction_buff = lambda sim, instance, is_positive: 'ww_caught_buff'
# component functions: 4 + 3 + 2 + 1 = 10, matching get_sex_satisfaction_level
satis_mod._get_sim_base_sex_satisfaction_value = lambda sim, inst, target: 4
satis_mod._get_sim_dynamic_sex_satisfaction_value = lambda sim, inst: 3
satis_mod._get_targets_base_sex_satisfaction_value = lambda sim, inst, target: 2
satis_mod._get_targets_dynamic_sex_satisfaction_value = lambda sim, inst, target: 1

# Animation roles. WickedWhims resolves a Sim's admissible slot genders here,
# and everything that assigns Sims to animation slots reads the result.
MALE, FEMALE, BOTH = 1, 11, 50
gender_mod = make_module('wickedwhims.sex.enums.sex_gender')
gender_mod.get_sim_sex_genders = lambda sim, ignore=False, both=None: (MALE,)
# BOTH fits either slot, so it counts as male-fitting -- that is what makes it
# the interesting case for without_male_roles.
# The root: get_sim_sex_genders calls this, and so does set_animation_instance
# when it decides which Sim takes which animation slot.
gender_mod.get_sim_native_sex_gender = lambda sim, ignore=False: (
    FEMALE if sim in ('caged', 'free_female') else MALE)
gender_mod.is_male_sex_gender = lambda g: g in (MALE, BOTH)
gender_mod.is_female_sex_gender = lambda g: g in (FEMALE, BOTH)
gender_mod.get_opposite_sex_gender_variant = lambda g: {MALE: FEMALE, FEMALE: MALE}.get(g, g)
# a module that did `from sex_gender import get_sim_sex_genders` before us
gender_importer = make_module('wickedwhims.fake_gender_caller')
gender_importer.get_sim_sex_genders = gender_mod.get_sim_sex_genders

# WickedWhims' settings menu, mirroring what was read out of its bytecode:
# elements live in a plain list, rows are enumerated AT OPEN, and the callback
# dispatches by index into that same list.
OPENED = []


class FakeBranch(object):
    """A branch row: no setting_identifier, like WickedWhims' own."""
    def __init__(self, name, callback_name=None):
        self.option_name = None
        self.selected = 0
        if callback_name:
            def cb():
                return name
            cb.__name__ = callback_name
            self.branch_window_callback = cb

    def _select(self):
        self.selected += 1
        return 'branch'


class FakeElement(object):
    def __init__(self, name, setting_identifier=None):
        self.option_name = name
        if setting_identifier is not None:
            self.setting_identifier = setting_identifier
        self.selected = 0

    def _select(self):
        self.selected += 1
        return self.option_name


class FakeSettingsWindow(object):
    def __init__(self, window_id, title='t', description='d'):
        self.window_id = window_id
        self.title = title
        self.description = description
        self.elements = []

    def add_element(self, element):
        self.elements.append(element)

    def open(self, *a, **kw):
        # what WickedWhims does: enumerate(self.elements) into the dialog
        OPENED.append([e.option_name for e in self.elements])
        return list(enumerate(self.elements))

    def _window_callback(self, element_index):
        return self.elements[element_index]._select()


settings_ui_mod = make_module('wickedwhims.main.settings.settings_builder')
settings_ui_mod.SettingsWindow = FakeSettingsWindow
settings_ui_mod.SettingsBranchElement = FakeElement
settings_ui_mod.SettingsSwitchElement = FakeElement
settings_ui_mod.SettingsSelectElement = FakeElement
settings_ui_mod.SettingsCustomCallbackElement = FakeElement
settings_ui_mod.SettingsInputElement = FakeElement

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

check('module imports', wickedbridge.VERSION == '0.13.0')
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
check('all compat symbols resolved', len(bootstrap.compat.missing()) == 0,
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
check('every declared gate installed',
      len(gates._installed) == len(gates.GATES), str(gates._installed))
check('sex.allow_sim is gone -- it could not enforce anything',
      'sex.allow_sim' not in [g[0] for g in gates.GATES]
      and 'sex.allow_sim' not in wickedbridge.GATES)
check('gate wrapper reached the importing module too',
      gate_importer.is_sim_sex_appropriate is sims_mod.is_sim_sex_appropriate)
check('un-gated predicate still returns WW answer',
      sims_mod.is_sim_sex_appropriate('sim_x') is True)

denied = {'called': 0}
def deny_chastity(sim):
    denied['called'] += 1
    return False if sim == 'chaste_sim' else None

wickedbridge.gate('sex.appropriate', deny_chastity)
check('veto denies for the targeted Sim',
      sims_mod.is_sim_sex_appropriate('chaste_sim') is False)
check('abstain passes through to WickedWhims',
      sims_mod.is_sim_sex_appropriate('other_sim') is True)
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

print('--- 0.4.0 additions ---')
check('after_stop driven by game update, not the tick chain', len(GAME_UPDATE) == 1)
posted = []
wickedbridge.subscribe('sex.after_stop', lambda h: posted.append(h.id))
fourth = FakeSexInstance(ssid=3003, actors=['x'])
handlers_mod.register_active_sex_instance(fourth)
handlers_mod.unregister_active_sex_instance(fourth)
check('after_stop not fired immediately on stop', len(posted) == 0)
for _ in range(sex.AFTER_STOP_DELAY_TICKS):
    GAME_UPDATE[0](1)
check('after_stop fires after the delay', len(posted) == 1)

check('cumulative act counter survives handle release', sex._counts['acts'] >= 4,
      'got %d' % sex._counts['acts'])

class Cancellable(FakeSexInstance):
    def __init__(self, *a, **k):
        FakeSexInstance.__init__(self, *a, **k); self.cancelled = None
    def cancel(self, reason=None): self.cancelled = reason
c = Cancellable(ssid=4004, actors=['y'])
check('handle.cancel reaches the instance',
      sex._handle_for(c).cancel('testing') and c.cancelled == 'testing')

from wickedbridge import settings as _s
check('settings read by name without importing WW enums',
      _s.sex('CUM_SWITCH_STATE') == 'ON')
check('unknown setting returns the default, never raises',
      _s.sex('NO_SUCH_SETTING', 'fallback') == 'fallback')
check('settings.names lists available members',
      'CUM_SWITCH_STATE' in _s.names('sex'))

check('gates use the live subscriber list (no per-call copy)',
      events.raw_subscribers('sex.appropriate') is not None)

print('--- satisfaction ---')
from wickedbridge import satisfaction as _sat
check('all 5 satisfaction hooks installed', len(_sat._installed) == 5, str(_sat._installed))

computed = []
wickedbridge.subscribe('satisfaction.computed', lambda inst: computed.append(inst))
satis_mod.run_post_sex_satisfaction('inst')
check('satisfaction.computed fires on the post-sex pass', len(computed) == 1)

check('level passes through untouched with no resolver',
      satis_mod.get_sex_satisfaction_level('sim', 'inst', 'target') == 10)

# scale rather than replace -- WickedWhims' own value is the last argument
wickedbridge.resolve('satisfaction.level',
                     lambda sim, inst, target, ww: ww * 0.5 if sim == 'loose' else None)
check('resolver scales WickedWhims value for the targeted Sim',
      satis_mod.get_sex_satisfaction_level('loose', 'inst', 'target') == 5.0)
check('abstaining resolver leaves WickedWhims value intact',
      satis_mod.get_sex_satisfaction_level('other', 'inst', 'target') == 10)

# the Exhibitionist pattern: swap which buff is applied
wickedbridge.resolve('satisfaction.buff',
                     lambda sim, inst, pos, ww: 'flirty_buff' if sim == 'shameless' else None)
check('resolver substitutes the satisfaction buff',
      stypes_mod.get_sex_satisfaction_buff('shameless', 'inst', True) == 'flirty_buff')
check('other Sims keep WickedWhims buff',
      stypes_mod.get_sex_satisfaction_buff('normal', 'inst', True) == 'ww_caught_buff')

def bad_resolver(sim, inst, target, ww):
    raise RuntimeError('resolver bug')
wickedbridge.resolve('satisfaction.pair_level', bad_resolver)
check('a throwing resolver falls back to WickedWhims value',
      satis_mod.get_sims_sex_satisfaction_level('a', 'b', 'inst') == 20)

wickedbridge.gate('satisfaction.allowed', lambda inst: False)
check('satisfaction can be gated off entirely',
      satis_mod._is_allowed_sex_satisfaction('inst') is False)

print('--- keyed satisfaction model ---')
from wickedbridge import satisfaction_model as _sm, compat
check('default keys registered', set(_sm.keys()) >=
      {'mood_motives_traits', 'exposed', 'exhibitionism', 'partner', 'lube'},
      str(sorted(_sm.keys())))

seeded = _sm.seed('sim', 'inst', 'target')
check('seeded from WickedWhims own component functions',
      seeded == {'mood_motives_traits': 4, 'exhibitionism': 3, 'partner': 2, 'lube': 1},
      str(seeded))
check('every seeded value is a magnitude, never signed',
      all(v >= 0 for v in seeded.values()), str(seeded))
total, _b = _sm.compute('sim', 'inst', 'target')
check('model recombines to WickedWhims total with no mods', total == 10, 'got %s' % total)

# --- polarity: sign belongs to the key, not to anything a mod passes in -----
check('exposed and exhibitionism are separate keys with opposite polarity',
      _sm.keys()['exposed']['polarity'] == -1 and
      _sm.keys()['exhibitionism']['polarity'] == 1)
check('a negative WW seed routes to the opposite key of the pair',
      _sm.keys()['exhibitionism']['seed_negative_to'] == 'exposed')

satis_mod._get_sim_dynamic_sex_satisfaction_value = lambda sim, inst: -3
compat.scan(force=True)
seeded = _sm.seed('sim', 'inst', 'target')
check('a disapproved-of Sim seeds exposed, not a negative exhibitionism',
      seeded.get('exposed') == 3 and 'exhibitionism' not in seeded, str(seeded))
neg_total, _b = _sm.compute('sim', 'inst', 'target')
check('routed seed still reproduces WickedWhims total (4 - 3 + 2 + 1)',
      neg_total == 4, 'got %s' % neg_total)
satis_mod._get_sim_dynamic_sex_satisfaction_value = lambda sim, inst: 3
compat.scan(force=True)

# Both mods contribute POSITIVE 3, as the design requires; the keys decide
# which way each one pulls.
wickedbridge.modify('satisfaction', lambda s_, i_, t_: {'exposed': 3})
wickedbridge.modify('satisfaction', lambda s_, i_, t_: {'exhibitionism': 3})
total, b = _sm.compute('sim', 'inst', 'target')
check('a positive contribution to a negative key subtracts',
      b['exposed'][0] == 3 and b['exposed'][2] == -3, str(b['exposed']))
check('a positive contribution to a positive key adds',
      b['exhibitionism'][2] > 0, str(b['exhibitionism']))

before = dict(_sm._rejected)
wickedbridge.modify('satisfaction', lambda s_, i_, t_: {'exposed': -5})
total, b = _sm.compute('sim', 'inst', 'target')
check('negative modifiers are rejected, not applied',
      _sm._rejected.get('negative_modifier', 0) > before.get('negative_modifier', 0)
      and b['exposed'][0] == 3, str(b['exposed']))

# The exhibitionist shape the user described: mute the cost with a 0 scaler,
# earn from your own key. No sign flip anywhere.
wickedbridge.scale('satisfaction', lambda s_, i_, t_: {'exposed': 0.0})
total, b = _sm.compute('sim', 'inst', 'target')
check('a 0 scaler mutes the cost rather than inverting it',
      b['exposed'][2] == 0.0 and b['exhibitionism'][2] > 0, str(b['exposed']))

wickedbridge.modify('satisfaction', lambda s_, i_, t_: {'watched': 5})  # unknown key on purpose
wickedbridge.modify('satisfaction', lambda s_, i_, t_: {'watched': 2, 'partner': 1})
total, b = _sm.compute('sim', 'inst', 'target')
check('modifiers sum per key across mods (5 + 2)', b['watched'][0] == 7, str(b['watched']))
check('seeded key sums WW seed plus contributions',
      b['partner'][0] == 3, 'seed 2 + mod 1 = %s' % (b['partner'][0],))

wickedbridge.scale('satisfaction', lambda s_, i_, t_: {'watched': 0.0})
total, b = _sm.compute('sim', 'inst', 'target')
check('a lone 0 scaler zeroes the key when nobody disagrees',
      b['watched'][1] == 0.0, 'got %s' % (b['watched'][1],))
wickedbridge.scale('satisfaction', lambda s_, i_, t_: {'watched': 1.0})
total, b = _sm.compute('sim', 'inst', 'target')
check('0 MUTES rather than annihilates once another mod disagrees',
      abs(b['watched'][1] - 0.5) < 1e-9, 'got %s' % (b['watched'][1],))

before = dict(_sm._rejected)
wickedbridge.scale('satisfaction', lambda s_, i_, t_: {'watched': -2.0})
_sm.compute('sim', 'inst', 'target')
check('negative scalers are rejected -- sign belongs to the key',
      _sm._rejected.get('negative_scaler', 0) > before.get('negative_scaler', 0))
wickedbridge.scale('satisfaction', lambda s_, i_, t_: {'watched': 999.0})
_sm.compute('sim', 'inst', 'target')
check('absurd scalers are clamped, not honoured', _sm._rejected.get('clamped', 0) > 0)

wickedbridge.modify('satisfaction', lambda s_, i_, t_: {'typo_key': 99})
_sm.compute('sim', 'inst', 'target')
check('unknown keys are recorded, not silently inert', 'typo_key' in _sm.unknown_keys())

def bad(s_, i_, t_):
    raise RuntimeError('contributor bug')
wickedbridge.modify('satisfaction', bad)
t2, _ = _sm.compute('sim', 'inst', 'target')
check('a throwing contributor does not break the model', isinstance(t2, (int, float)))

from wickedbridge import satisfaction as _sat
check('model is observe-only in this build', _sat.MODEL_REPLACES_WW is False)
satis_mod.get_sex_satisfaction_level('sim', 'inst', 'target')
check('WickedWhims value still returned while observing',
      _sat.model_stats()['samples'] >= 1)

print('--- animation roles ---')
from wickedbridge import roles
check('both role resolvers installed',
      sorted(roles._installed) == sorted([roles.EV_SIM_GENDER,
                                          roles.EV_SIM_GENDERS]),
      str(roles._installed))
check('wrapper reached the importing module too',
      gender_importer.get_sim_sex_genders is gender_mod.get_sim_sex_genders)
check('untouched value passes through',
      gender_mod.get_sim_sex_genders('sim') == (MALE,))

wickedbridge.resolve('sex.sim_genders',
                     lambda sim, *rest: (FEMALE,) if sim == 'caged' else None)
check('a subscriber can narrow which roles a Sim fits',
      gender_mod.get_sim_sex_genders('caged') == (FEMALE,))
check('abstaining leaves WickedWhims answer alone',
      gender_mod.get_sim_sex_genders('free') == (MALE,))
check('narrowing is counted', roles.counts()['narrowed'] >= 1)

before = roles.counts()['refused_empty']
wickedbridge.resolve('sex.sim_genders',
                     lambda sim, *rest: () if sim == 'empty' else None)
check('an empty replacement is refused -- a Sim must fit some role',
      gender_mod.get_sim_sex_genders('empty') == (MALE,)
      and roles.counts()['refused_empty'] == before + 1)

wickedbridge.resolve('sex.sim_genders',
                     lambda sim, *rest: (BOTH,) if sim == 'chain' else None)
wickedbridge.resolve('sex.sim_genders',
                     lambda sim, *rest: rest[-1] + (FEMALE,) if sim == 'chain' else None)
check('two mods each narrow in turn, second sees the first answer',
      gender_mod.get_sim_sex_genders('chain') == (BOTH, FEMALE),
      str(gender_mod.get_sim_sex_genders('chain')))


def _bad_role(*a):
    raise RuntimeError('resolver bug')


wickedbridge.resolve('sex.sim_genders', _bad_role)
check('a throwing resolver does not break role resolution',
      gender_mod.get_sim_sex_genders('free') == (MALE,))
check('sex.sim_genders is advertised as a resolver',
      roles.EV_SIM_GENDERS in wickedbridge.RESOLVERS)

check('a male-only Sim is mapped to the female role, not emptied',
      wickedbridge.without_male_roles((MALE,)) == (FEMALE,),
      str(wickedbridge.without_male_roles((MALE,))))
check('a Sim with a female role keeps it and loses only the male one',
      wickedbridge.without_male_roles((MALE, FEMALE)) == (FEMALE,),
      str(wickedbridge.without_male_roles((MALE, FEMALE))))
check('a female-only Sim is untouched',
      wickedbridge.without_male_roles((FEMALE,)) == (FEMALE,))
before_nf = roles.counts()['no_female_role']
check('a Sim with no reachable female role is left alone, not broken',
      wickedbridge.without_male_roles((BOTH,)) == (BOTH,)
      and roles.counts()['no_female_role'] == before_nf + 1)
# The bug this hook exists for: narrowing only the tuple filtered which
# animations were offered, while set_animation_instance kept assigning slots
# from the unnarrowed native gender -- so a caged Sim still took the male role.
wickedbridge.resolve('sex.sim_gender',
                     lambda sim, *rest: (wickedbridge.without_male_role(rest[-1])
                                         if sim == 'locked' else None))
check('the native gender is narrowed too, which is what picks the slot',
      gender_mod.get_sim_native_sex_gender('locked') == FEMALE,
      str(gender_mod.get_sim_native_sex_gender('locked')))
check('an unaffected Sim keeps their native gender',
      gender_mod.get_sim_native_sex_gender('someone') == MALE)
# That the real get_sim_sex_genders composes on top of the narrowed root is a
# property of WickedWhims' own module-global lookup, read out of its bytecode
# -- the stub here returns a constant, so asserting it would only be testing
# the stub. What the harness can honestly check is that the two hooks are
# installed over different functions and count separately.
check('the two hooks wrap different functions',
      gender_mod.get_sim_native_sex_gender is not gender_mod.get_sim_sex_genders)
check('the native hook is counted separately from the tuple hook',
      roles.counts()['native_narrowed'] >= 1)
check('without_male_role maps one gender, without a constant',
      wickedbridge.without_male_role(MALE) == FEMALE
      and wickedbridge.without_male_role(FEMALE) == FEMALE)

check('the helpers need no SexGenderType constant from the caller',
      wickedbridge.is_male_role(MALE) and not wickedbridge.is_male_role(FEMALE)
      and wickedbridge.opposite_role(MALE) == FEMALE)

print('--- settings menu ---')
from wickedbridge import menu
check('menu hook installed', menu._installed == ['settings.menu'],
      str(menu._installed))


def _window():
    w = FakeSettingsWindow('gender_recognition')
    for name in ('behaviour', 'advanced', 'fit_to_orientation'):
        w.add_element(FakeElement(name, setting_identifier=name))
    return w


del OPENED[:]
w = _window()
w.open()
check('an untouched window opens unchanged',
      OPENED[-1] == ['behaviour', 'advanced', 'fit_to_orientation'], str(OPENED[-1]))
check('the window was observed, so its ids are discoverable',
      menu.observed().get('gender_recognition') ==
      ['behaviour', 'advanced', 'fit_to_orientation'], str(menu.observed()))

h1 = menu.remove('gender_recognition', 'advanced')
w = _window(); w.open()
check('remove takes the node out',
      OPENED[-1] == ['behaviour', 'fit_to_orientation'], str(OPENED[-1]))

h2 = menu.remove('gender_recognition', 'advanced')
w = _window(); w.open()
check('five mods removing one node agree -- removal is idempotent',
      OPENED[-1] == ['behaviour', 'fit_to_orientation'], str(OPENED[-1]))

h3 = menu.reserve('gender_recognition', 'advanced')
w = _window(); w.open()
check('reserve outranks any number of removals',
      OPENED[-1] == ['behaviour', 'advanced', 'fit_to_orientation'], str(OPENED[-1]))
check('mutations() records the veto, not just the removal',
      any(m['kind'] == 'remove' and 'vetoed' in m['outcome']
          for m in menu.mutations()), str(menu.mutations()))
check('remove and reserve handles are distinguishable',
      h1[0] == 'remove' and h3[0] == 'reserve')
check('withdrawing the reservation does not delete the removal',
      menu.withdraw(h3) and ('gender_recognition', 'advanced') in menu._removals)
check('withdrawing one mod declaration leaves the other mod alone',
      menu.withdraw(h2) and ('gender_recognition', 'advanced') in menu._removals)
check('withdrawing the same handle twice is not a second removal',
      menu.withdraw(h2) is False)

# The invariant that matters: dispatch is by index into the same list the rows
# were enumerated from. A mutation that renumbered one but not the other would
# fire the wrong menu item -- silently, and looking like a WickedWhims bug.
w = _window()
rows = w.open()
for index, element in rows:
    check('row %d dispatches to the element it displays' % index,
          w._window_callback(index) == element.option_name)

menu.upsert('gender_recognition', lambda: FakeElement('mod_a'), key='a')
menu.upsert('gender_recognition', lambda: FakeElement('mod_b'), key='b')
w = _window(); w.open()
check('upserts from several mods union rather than clobber',
      OPENED[-1] == ['behaviour', 'fit_to_orientation', 'mod_a', 'mod_b'],
      str(OPENED[-1]))

w = _window()
rows = w.open()
check('indices still line up after removals and upserts',
      all(w._window_callback(i) == e.option_name for i, e in rows))

check('upsert keys default to the declaring mod, so two mods cannot collide',
      len(set(k[1] for k in menu._upserts)) == len(menu._upserts))

w = _window(); w.open(); first = list(OPENED[-1])
w = _window(); w.open()
check('reopening a window does not compound edits', OPENED[-1] == first,
      '%s vs %s' % (OPENED[-1], first))

bad_handle = menu.upsert('gender_recognition', lambda: 1 / 0, key='bad')
w = _window(); w.open()
check('a throwing factory is counted, not raised',
      menu._counts['failed'] >= 1 and 'behaviour' in OPENED[-1])
menu.withdraw(bad_handle)

check('a window nobody declared against is untouched',
      (FakeSettingsWindow('other').open(), OPENED[-1] == [])[1])
check('menu verbs are on the public surface',
      all(hasattr(wickedbridge, n) for n in
          ('menu_remove', 'menu_reserve', 'menu_upsert', 'menu_withdraw',
           'menu_observed', 'menu_mutations', 'menu_classes')))
check('classes() exposes WickedWhims constructors so mods need not import them',
      'SettingsWindow' in wickedbridge.menu_classes())

# The console cannot be copied from, so the ids have to reach the status file.
lines, index = menu.listing()
report = chr(10).join(menu.report_lines())
check('the observed tree is numbered for the cheats',
      '[0.0]' in chr(10).join(lines) and '0.0' in index, str(lines[:3]))
check('the same listing reaches the status report, so it can be read from disk',
      all(line in report for line in lines), report)
check('window ids are rendered with repr, so their type is visible',
      "'gender_recognition'" in report, report)

# The bug from the first live run: several branch rows carry no
# setting_identifier, element_key returned None for all of them, and removing
# one None-keyed element stripped every other one in the window.
print('--- unkeyed elements ---')
menu._removals.clear(); menu._reservations.clear(); menu._upserts.clear()
menu._observed.clear(); menu._bases.clear()


def _mixed():
    w = FakeSettingsWindow('sex_interaction')
    w.add_element(FakeElement('teen_sex', setting_identifier='teen_sex'))
    w.add_element(FakeBranch('gender_recognition', 'open_gender_recognition'))
    w.add_element(FakeBranch('nameless_a'))
    w.add_element(FakeBranch('nameless_b'))
    return w


del OPENED[:]
w = _mixed(); w.open()
check('a window of mostly unkeyed rows opens intact', len(OPENED[-1]) == 4)
check('element_key never matches None against an unkeyed element',
      menu._matches(None, FakeBranch('x')) is False)

_lines, idx = menu.listing()
check('a branch is keyed by the callback that opens it',
      idx['0.1'][1] == 'callback:open_gender_recognition', str(idx['0.1']))
check('rows with no key at all are handed a positional match',
      idx['0.2'][1] == ('#', 2) and idx['0.3'][1] == ('#', 3), str(idx))

window_id, match, _i = idx['0.2']
menu.remove(window_id, match)
w = _mixed(); w.open()
check('removing one unkeyed row removes exactly one -- not every unkeyed row',
      len(OPENED[-1]) == 3, str(OPENED[-1]))

menu._removals.clear()
window_id, match, _i = idx['0.1']
menu.remove(window_id, match)
w = _mixed(); w.open()
check('removing a branch by its callback name removes only that branch',
      len(OPENED[-1]) == 3, str(OPENED[-1]))
w = _mixed(); rows = w.open()
check('indices still dispatch correctly after an unkeyed removal',
      all(w._window_callback(i) is not None for i, _e in rows))
menu._removals.clear()

print()
print('%d passed, %d failed' % (len(PASS), len(FAIL)))
if FAIL:
    print('FAILED: %s' % ', '.join(FAIL))
sys.exit(1 if FAIL else 0)
