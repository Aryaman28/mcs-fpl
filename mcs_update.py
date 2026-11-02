"""
MCS League updater
Run this once after each gameweek deadline to bake live FPL data into
index.html. Share that file with anyone — it works offline.

Usage:
    python mcs_update.py
"""

import sys, re, json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

# ── auto-install requests if missing ──────────────────────────────────
try:
    import requests
except ImportError:
    print("Installing 'requests'...")
    import subprocess
    subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'requests'])
    import requests

# ── config ────────────────────────────────────────────────────────────
LEAGUE_ID = 409139
BASE      = 'https://fantasy.premierleague.com/api/'
_candidates = [Path(__file__).parent / 'index.html', Path(__file__).parent / 'jdfc_league.html']
HTML_FILE = next((p for p in _candidates if p.exists()), _candidates[0])
HEADERS   = {'User-Agent': 'Mozilla/5.0 (compatible; JDFC-updater/1.0)'}

# ── helpers ───────────────────────────────────────────────────────────
def fpl(path):
    r = requests.get(BASE + path, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()

def par_fetch(paths):
    results = [None] * len(paths)
    with ThreadPoolExecutor(max_workers=12) as ex:
        futs = {ex.submit(fpl, p): i for i, p in enumerate(paths)}
        for fut in as_completed(futs):
            results[futs[fut]] = fut.result()
    return results

# ── fetch ─────────────────────────────────────────────────────────────
print('Fetching bootstrap...')
bootstrap = fpl('bootstrap-static/')

print('Fetching standings...')
league   = fpl(f'leagues-classic/{LEAGUE_ID}/standings/')
managers = league['standings']['results']

current_gw = next((e['id'] for e in bootstrap['events'] if e['is_current']), None)
if not current_gw:
    nxt = next((e['id'] for e in bootstrap['events'] if e['is_next']), None)
    current_gw = (nxt - 1) if nxt else 1

print(f'Current gameweek: GW{current_gw}')

entry_ids = [m['entry'] for m in managers]
paths = (
    [f'event/{current_gw}/live/'] +
    [f'entry/{eid}/event/{current_gw}/picks/' for eid in entry_ids] +
    [f'entry/{eid}/history/'                  for eid in entry_ids]
)

print(f'Fetching live data + picks + history for {len(entry_ids)} managers...')
results    = par_fetch(paths)
live_data  = results[0]
all_picks  = results[1 : 1 + len(entry_ids)]
all_history = results[1 + len(entry_ids):]

# ── slim down bootstrap (keep only fields the HTML needs) ─────────────
elements_slim = [
    {'id': e['id'], 'web_name': e['web_name'], 'code': e['code'],
     'team': e['team'], 'element_type': e['element_type']}
    for e in bootstrap['elements']
]
teams_slim = [
    {'id': t['id'], 'name': t['name'], 'short_name': t['short_name'], 'code': t['code']}
    for t in bootstrap['teams']
]

# ── build payload ─────────────────────────────────────────────────────
payload = {
    'currentGW':    current_gw,
    'managers':     managers,
    'allPicks':     all_picks,
    'allHistory':   all_history,
    'liveElements': live_data['elements'],
    'elements':     elements_slim,
    'teams':        teams_slim,
}
data_json = json.dumps(payload, separators=(',', ':'), ensure_ascii=False)

# ── inject into HTML ──────────────────────────────────────────────────
html = HTML_FILE.read_text(encoding='utf-8')

# Replace whatever is between "PRELOADED_DATA = " and "; // JDFC_DATA_MARKER"
# (handles both null and a previously injected blob)
new_html, n = re.subn(
    r'const PRELOADED_DATA = .*?; // JDFC_DATA_MARKER',
    f'const PRELOADED_DATA = {data_json}; // JDFC_DATA_MARKER',
    html,
    flags=re.DOTALL,
)

if n == 0:
    print('ERROR: marker not found in jdfc_league.html — is the file from this session?')
    sys.exit(1)

HTML_FILE.write_text(new_html, encoding='utf-8')

kb = len(data_json) // 1024
print(f'Done! {HTML_FILE.name} updated with GW{current_gw} data ({kb} KB injected).')
print(f'Share the file: {HTML_FILE}')
