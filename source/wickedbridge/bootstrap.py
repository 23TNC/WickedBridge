# -*- coding: utf-8 -*-
"""Installation and health reporting.

Silence from a Sims 4 script mod means "never imported", not "imported and did
nothing" -- so this writes a status file unprompted at import and again at zone
load. Everything here is best-effort: the bridge must never be the reason a
save fails to load.
"""

import sys

from . import compat, events, gates, menu, roles, satisfaction, settings, sex

VERSION = '0.13.0'
STATUS_FILE = 'WickedBridge_status.txt'

_state = {'imported': True, 'zone_load': 'not yet', 'install': 'not attempted'}


# --------------------------------------------------------------------------
# reporting
# --------------------------------------------------------------------------
def _candidate_paths(filename):
    import os
    paths = []
    base = 'C:' + os.sep + os.path.join('Users', 'Wolf', 'Documents',
                                        'Electronic Arts', 'The Sims 4')
    paths.append(os.path.join(base, filename))
    paths.append(os.path.join(base, 'Mods', filename))
    try:
        home = os.path.expanduser('~')
        paths.append(os.path.join(home, 'Documents', 'Electronic Arts',
                                  'The Sims 4', filename))
    except Exception:
        pass
    try:
        paths.append(os.path.join(os.getcwd(), filename))
    except Exception:
        pass
    return paths


def report():
    lines = ['--- WickedBridge %s ---' % VERSION,
             'module imported: %s' % _state['imported'],
             'zone load: %s' % _state['zone_load'],
             'install: %s' % _state['install'],
             '']
    lines += compat.report_lines()
    lines.append('')
    lines += sex.report_lines()
    lines.append('')
    lines += events.report_lines()
    lines.append('')
    lines += gates.report_lines()
    lines.append('')
    lines += roles.report_lines()
    lines.append('')
    lines += satisfaction.report_lines()
    lines.append('')
    lines += settings.report_lines()
    lines.append('')
    lines += menu.report_lines()
    return lines


def write_report():
    lines = report()
    for path in _candidate_paths(STATUS_FILE):
        try:
            with open(path, 'w') as handle:
                for line in lines:
                    handle.write(line)
                    handle.write(chr(10))
            return path
        except Exception:
            continue
    return None


def _wwlog(message):
    module = sys.modules.get(compat.M_LOGGER)
    logger = getattr(module, 'wlog', None) if module is not None else None
    if logger is None:
        return False
    try:
        logger.info('[WickedBridge] %s' % message)
        return True
    except Exception:
        return False


# --------------------------------------------------------------------------
# installation
# --------------------------------------------------------------------------
def install():
    """Resolve WickedWhims and append our tick handler. Idempotent."""
    compat.scan(force=True)      # WW may have loaded after our import
    if not compat.is_wickedwhims_loaded():
        _state['install'] = 'WickedWhims not loaded'
        return False
    required_missing = compat.missing(required_only=True)
    if required_missing:
        _state['install'] = 'missing required: %s' % ', '.join(m[0] for m in required_missing)
        return False
    ok = sex.install()
    lifecycle = sex.install_lifecycle()
    gates.install()
    sex.install_after_stop()
    satisfaction.install()
    roles.install()
    menu.install()
    if ok and lifecycle:
        _state['install'] = 'ok'
    elif ok:
        _state['install'] = 'ok (tick only -- no start/stop signals)'
    else:
        _state['install'] = 'FAILED to append tick handler'
    _wwlog(_state['install'])
    return ok


def _on_zone_load(*args, **kwargs):
    try:
        _state['zone_load'] = 'ok'
        install()
    except Exception as ex:
        _state['zone_load'] = 'FAILED: %r' % (ex,)
    try:
        write_report()
    except Exception:
        pass


def _register():
    """Prefer WickedWhims' own zone-load registration; fall back to EA's Zone."""
    register = compat.get('register_zone_load')
    if register is not None:
        try:
            register(unique_id='wickedbridge', late=True)(_on_zone_load)
            return 'turbolib2.register_zone_load_event_method'
        except Exception:
            pass
    try:
        import zone
        from functools import wraps
        original = zone.Zone.do_zone_spin_up

        @wraps(original)
        def _spin_up(self, *args, **kwargs):
            result = original(self, *args, **kwargs)
            _on_zone_load()
            return result

        zone.Zone.do_zone_spin_up = _spin_up
        return 'zone.Zone.do_zone_spin_up'
    except Exception as ex:
        return 'FAILED: %r' % (ex,)


def start():
    _state['zone_load'] = 'registered via %s' % _register()
    try:
        write_report()
    except Exception:
        pass
    _wwlog('imported, %s' % _state['zone_load'])


# --------------------------------------------------------------------------
# wickedbridge.status -- refresh and print the report on demand
# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
# menu test cheats
#
# Addressing by "window.element" index rather than by raw id, because window
# ids and element keys are whatever WickedWhims made them -- ints, enum
# members, localised-string hashes -- and a cheat cannot type them safely.
# Run wickedbridge.menu.list first; the numbers it prints are the handles.
# --------------------------------------------------------------------------
_menu_index = {}
_menu_handles = []


def _menu_list(output):
    from . import menu
    lines, index = menu.listing()
    _menu_index.clear()
    _menu_index.update(index)
    if not lines:
        output('no settings windows seen yet -- open WickedWhims settings and '
               'walk into the screens you care about, then run this again')
        return
    for line in lines:
        output(line)
    output('%d windows. Use e.g. wickedbridge.menu.remove 0.1'
           % len(menu.observed()))
    # The console cannot be copied from, so the same listing is written to the
    # status file every time.
    output('also written to: %s' % (write_report() or 'FAILED'))


def _menu_target(output, ref):
    if not _menu_index:
        output('run wickedbridge.menu.list first')
        return None
    target = _menu_index.get(ref)
    if target is None:
        output('no such entry %r -- run wickedbridge.menu.list' % ref)
    return target


try:
    import sims4.commands

    @sims4.commands.Command('wickedbridge.status',
                            command_type=sims4.commands.CommandType.Live)
    def _wickedbridge_status(_connection=None):
        output = sims4.commands.CheatOutput(_connection)
        for line in report():
            output(line)
        output('written to: %s' % (write_report() or 'FAILED'))
    @sims4.commands.Command('wickedbridge.menu.list',
                            command_type=sims4.commands.CommandType.Live)
    def _wb_menu_list(_connection=None):
        _menu_list(sims4.commands.CheatOutput(_connection))

    @sims4.commands.Command('wickedbridge.menu.remove',
                            command_type=sims4.commands.CommandType.Live)
    def _wb_menu_remove(ref: str = '', _connection=None):
        from . import menu
        output = sims4.commands.CheatOutput(_connection)
        target = _menu_target(output, ref)
        if target is None:
            return
        window_id, key, _i = target
        _menu_handles.append(menu.remove(window_id, key, reason='cheat'))
        write_report()
        write_report()
        write_report()
        output('declared remove of %r in %r -- reopen the window' % (key, window_id))

    @sims4.commands.Command('wickedbridge.menu.reserve',
                            command_type=sims4.commands.CommandType.Live)
    def _wb_menu_reserve(ref: str = '', _connection=None):
        from . import menu
        output = sims4.commands.CheatOutput(_connection)
        target = _menu_target(output, ref)
        if target is None:
            return
        window_id, key, _i = target
        _menu_handles.append(menu.reserve(window_id, key, reason='cheat'))
        output('declared reserve of %r -- reserve outranks remove' % (key,))

    @sims4.commands.Command('wickedbridge.menu.dupe',
                            command_type=sims4.commands.CommandType.Live)
    def _wb_menu_dupe(ref: str = '', _connection=None):
        from . import menu
        output = sims4.commands.CheatOutput(_connection)
        target = _menu_target(output, ref)
        if target is None:
            return
        window_id, key, index = target
        elements = menu.base_elements(window_id)
        if index >= len(elements):
            output('that window has changed since the listing')
            return
        element = elements[index]
        _menu_handles.append(
            menu.upsert(window_id, lambda element=element: element,
                        key='cheat_dupe_%s' % (ref,), reason='cheat'))
        output('declared upsert of a copy of %r -- it should appear twice, and '
               'BOTH copies must do the same thing when clicked' % (key,))

    @sims4.commands.Command('wickedbridge.menu.clear',
                            command_type=sims4.commands.CommandType.Live)
    def _wb_menu_clear(_connection=None):
        from . import menu
        output = sims4.commands.CheatOutput(_connection)
        dropped = sum(1 for h in _menu_handles if menu.withdraw(h))
        del _menu_handles[:]
        write_report()
        output('withdrew %d declaration(s) -- reopen the window to confirm it '
               'is back to stock' % dropped)

except Exception as ex:
    _wwlog('could not register status command: %r' % (ex,))
