# -*- coding: utf-8 -*-
"""drive_upload sin resumable-logikk, mot en falsk Google.

    python flow/worker/tests/test_drive_upload.py

Finnes fordi ordre 1512 doede paa en enkelt HTTP 500 i det avsluttende PUT-et
mot Google Drive. reprint_order avbryter paa foerste feil, saa hverken innmat
eller Gelato-utkast ble roert - av en feil som gikk over av seg selv.

Ingen nett og ingen legitimasjon: _OPENER byttes ut med en attrapp som svarer
slik Google gjoer - 500 midt i, 308 med Range paa statussporringen, utloept
sesjon, og til slutt 200 med fil-JSON.
"""
import io, json, os, sys, urllib.error

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
sys.modules['n8n_credential'] = type(sys)('n8n_credential')
sys.modules['n8n_credential'].load = lambda cid: {'data': {}}
import drive_upload as du

du._sleep = lambda attempt: None  # ingen ventetid i testen

PAYLOAD = b'%PDF-1.7\n' + b'x' * (5 * 1024 * 1024)


class Resp(io.BytesIO):
    def __init__(self, body=b'', headers=None):
        super().__init__(body)
        self.headers = headers or {}
    def __enter__(self): return self
    def __exit__(self, *a): return False


def http_error(code, headers=None):
    return urllib.error.HTTPError('u', code, 'nope', headers or {}, None)


class Fake:
    """script = liste med (forventet_metode, svar-eller-unntak)."""
    def __init__(self, script):
        self.script = list(script)
        self.seen = []
        self.received = 0
    def open(self, req, timeout=None):
        method = req.get_method()
        self.seen.append((method, req.headers.get('Content-range')))
        action = self.script.pop(0)
        if isinstance(action, Exception):
            raise action
        return action


def run(name, script, expect_id=None, expect_raises=None):
    fake = Fake(script)
    du._OPENER = fake
    try:
        res = du.upload('tok', PDF, 'parent')
    except BaseException as exc:
        if expect_raises and isinstance(exc, expect_raises):
            print('OK  %-42s -> %s' % (name, type(exc).__name__))
            return fake
        print('NEI %-42s -> uventet %r' % (name, exc))
        raise SystemExit(1)
    if expect_id and res.get('id') != expect_id:
        print('NEI %-42s -> fikk id %r' % (name, res.get('id')))
        raise SystemExit(1)
    print('OK  %-42s -> id=%s' % (name, res.get('id')))
    return fake


import tempfile
PDF = os.path.join(tempfile.mkdtemp(), 'Iver_cover.pdf')
open(PDF, 'wb').write(PAYLOAD)
SIZE = len(PAYLOAD)

session = lambda: Resp(b'', {'Location': 'https://upload/sesjon-1'})
done = lambda i='FIL123': Resp(json.dumps({'id': i, 'name': 'Iver_cover.pdf'}).encode())

# 1. Normalveien: sesjon + ett PUT.
run('rett igjennom', [session(), done()], 'FIL123')

# 2. Akkurat feilen fra ordre 1512: 500 paa PUT, saa gjenoppta og fullfoer.
f = run('HTTP 500, gjenopptar og fullfoerer',
        [session(),
         http_error(500),
         http_error(308, {'Range': 'bytes=0-%d' % (SIZE // 2 - 1)}),  # statussporring
         done()],
        'FIL123')
siste = f.seen[-1][1]
forventet = 'bytes %d-%d/%d' % (SIZE // 2, SIZE - 1, SIZE)
assert siste == forventet, 'gjenopptok fra feil sted: %r != %r' % (siste, forventet)
print('    ... sendte bare resten: %s' % siste)

# 3. Google rakk aa fullfoere selv om vi fikk 500 - ikke last opp igjen.
f = run('500, men fila var oppe likevel',
        [session(), http_error(500), done('ALLEREDE')], 'ALLEREDE')
assert len(f.seen) == 3, f.seen

# 4. Sesjonen utloept -> ny sesjon, ikke doeden.
run('sesjon utloept (410) -> ny sesjon',
    [session(), http_error(410), Resp(b'', {'Location': 'https://upload/sesjon-2'}),
     done()], 'FIL123')

# 5. Feil som ikke er vaar -> kastes videre med en gang, ingen 6 forsoek.
f = run('HTTP 403 kastes videre', [session(), http_error(403)],
        expect_raises=urllib.error.HTTPError)
assert len(f.seen) == 2, f.seen

# 6. Google er nede hele veien -> gir opp med tydelig beskjed.
script = [session()]
for _ in range(du.MAX_ATTEMPTS):
    script += [http_error(503), http_error(308, {'Range': 'bytes=0-9'})]
f = run('503 hele veien -> gir opp', script, expect_raises=SystemExit)
puts = [s for s in f.seen if s[1] and s[1].startswith('bytes ')
        and not s[1].startswith('bytes */')]
assert len(puts) == du.MAX_ATTEMPTS, 'proevde %d ganger' % len(puts)
print('    ... proevde %d ganger foer den ga opp' % len(puts))

# 7. Tom fil skal aldri naa Google.
open(PDF, 'wb').write(b'')
run('tom PDF avvises', [], expect_raises=SystemExit)

print('\nalle 7 testene bestaatt')
