import zipfile, os, glob, hashlib, py_compile

MODS = os.path.join(os.path.expanduser('~'), 'Documents', 'Electronic Arts',
                    'The Sims 4', 'Mods', 'WickedBridge')
os.makedirs(MODS, exist_ok=True)


def build(target, entries):
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as z:
        for src, arc in entries:
            z.write(src, arc)
    digest = hashlib.sha256(open(target, 'rb').read()).hexdigest()[:12]
    with zipfile.ZipFile(target) as z:
        names = z.namelist()
        bad = z.testzip()
    print('%s  %s  %d files  %s' % (os.path.basename(target), digest, len(names),
                                    'CORRUPT' if bad else 'ok'))
    return names


# Recompile rather than zipping whatever .pyc happens to be lying around.
# Skipping this once shipped an archive with a byte-identical hash to the
# previous build, which read as "nothing changed" instead of "nothing was
# rebuilt".
import compileall, shutil, sys
if sys.version_info[:2] != (3, 7):
    raise SystemExit('run this with Python 3.7 -- the game ignores other bytecode')
shutil.rmtree('wickedbridge/__pycache__', ignore_errors=True)
for stale in glob.glob('wickedbridge/*.pyc'):
    os.remove(stale)
if not compileall.compile_dir('wickedbridge', legacy=True, quiet=1):
    raise SystemExit('compile failed')

pycs = sorted(glob.glob('wickedbridge/*.pyc'))
assert pycs, 'no .pyc -- compile with Python 3.7 first'
names = build(os.path.join(MODS, 'WickedBridge.ts4script'),
              [(p, p.replace(os.sep, '/')) for p in pycs])
print('   ' + ', '.join(n.split('/')[-1] for n in names))
build(os.path.join(MODS, 'HelloWickedBridge.ts4script'),
      [('example/hello_wickedbridge.pyc', 'hello_wickedbridge.pyc')])

# Verify the DEPLOYED bytes really are Python 3.7 bytecode, not source that
# would be silently ignored, and not a stale copy of an earlier build.
import importlib.util
magic = importlib.util.MAGIC_NUMBER
with zipfile.ZipFile(os.path.join(MODS, 'WickedBridge.ts4script')) as z:
    heads = {n: z.read(n)[:4] for n in z.namelist()}
print('all entries carry the 3.7 magic: %s'
      % all(h == magic for h in heads.values()))
