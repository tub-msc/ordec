# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Scoreboard service for ORDeC Hub workshop competitions.

Runs as a JupyterHub-managed service (see jupyterhub_config.py), proxied at
/services/scoreboard/. The competition course in the ORDeC frontend
(web/src/scoreboard.js) talks to the JSON API here: a team claims a name
when the course opens, the Scoreboard panel polls the standings, and every
rebuild pushes its state: the score (supply current in uA, lowest wins) when
all checks pass, else no score, plus the .ord source and schematic as audit
trail. The guest identity from hub OAuth
binds entry and session; a secret the frontend generates and keeps in the
browser's localStorage re-claims the name from a new session after the
ephemeral guest was culled.

The projector page (for the beamer) doubles as the admin panel: when an
admin opens it, the leaderboard links each team to its page (pushed source
and schematic), shows the time of the last push and offers to delete
entries, and controls for final scoring appear below it. "Final scoring"
freezes the board and re-runs every submission against the pristine
harness (rescore.py) in a throwaway container of the user image, started
through the docker socket with the spawner's isolation settings; the
projector then shows the verified ranking until "Back to live scores"
lifts the freeze.

Entries are keyed by an integer id: the team name is a display name that
the team can change, and the guest identity is rebound on every re-claim.

Everything participant-controlled (team names, pushed source) is untrusted:
this service shares its origin with /hub/admin, so output escaping and the
CSP below are security boundaries, not cosmetics.
"""

import io
import json
import os
import secrets
import sqlite3
import tarfile
import time
import traceback
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlparse

import docker
import requests

from tornado import ioloop, web
from tornado.template import Template
from jupyterhub.services.auth import HubOAuthenticated, HubOAuthCallbackHandler
from jupyterhub.utils import url_path_join

PREFIX = os.environ['JUPYTERHUB_SERVICE_PREFIX']

TEAM_MAXLEN = 24
SECRET_MAXLEN = 64
SOURCE_MAXLEN = 200_000
SVG_MAXLEN = 1_000_000

# Final scoring container: the user image with the spawner's isolation
# settings (jupyterhub_config.py passes them into this service's environment).
IMAGE = os.environ.get('ORDEC_HUB_IMAGE', 'ordec-hub-user')
RUNTIME = os.environ.get('ORDEC_HUB_RUNTIME', 'io.containerd.kata.v2')
MEM_LIMIT = os.environ.get('ORDEC_HUB_MEM_LIMIT', '2G')
CPU_LIMIT = float(os.environ.get('ORDEC_HUB_CPU_LIMIT', '2'))
RESCORE_SRC = Path(__file__).with_name('rescore.py').read_bytes()
WORKDIR = '/home/app'   # the user image's working directory (inputs go here)
RESCORE_TIMEOUT = 120   # per submission, must match rescore.py TIMEOUT
RESCORE_SETUP = 600     # plus image start (Kata boot, PDK load)

db = sqlite3.connect(os.environ.get('ORDEC_SCOREBOARD_DB', 'scoreboard.sqlite'))
# The secret is stored in plain text: it is a per-browser re-claim token for
# a workshop afternoon, not a password. score, source and svg (the
# schematic as pushed) are NULL until the first push; score is NULL again
# whenever the latest build failed a check.
db.execute("""
    CREATE TABLE IF NOT EXISTS entries (
        id INTEGER PRIMARY KEY,
        team TEXT NOT NULL UNIQUE,
        secret TEXT NOT NULL,
        guest TEXT NOT NULL UNIQUE,
        score REAL,
        source TEXT,
        svg TEXT,
        updated TEXT NOT NULL
    )""")
# Final scoring: a row here freezes the board (pushes are refused). result
# is NULL while rescore.py runs, then its JSON result list, or {"error"} if
# the run failed; "Back to live scores" deletes the row.
db.execute("""
    CREATE TABLE IF NOT EXISTS final (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        started TEXT NOT NULL,
        result TEXT
    )""")
# A run does not survive a hub restart (the service is a hub subprocess):
# report it as failed rather than showing "running" forever.
db.execute("UPDATE final SET result = ? WHERE result IS NULL",
    (json.dumps({'error': "interrupted by a hub restart; run it again"}),))
db.commit()


def standings():
    """(id, team, score, updated) rows; ranked first, unscored teams last."""
    return db.execute(
        "SELECT id, team, score, updated FROM entries "
        "ORDER BY score IS NULL, score ASC, updated ASC").fetchall()


def team_of(guest):
    """The team name bound to guest, or None."""
    row = db.execute("SELECT team FROM entries WHERE guest = ?",
        (guest,)).fetchone()
    return row[0] if row else None


def claim(team, secret, guest):
    """
    Claim a team name, re-claim it by secret, or rename the entry this
    guest already holds (its score and source stay); returns an error or
    None.
    """
    now = time.strftime('%H:%M:%S')
    row = db.execute("SELECT secret FROM entries WHERE team = ?",
        (team,)).fetchone()
    other = team_of(guest)
    if other is not None and other != team:
        # One entry per session (score pushes are keyed on the guest
        # identity alone), so this is a rename of that entry.
        if final() is not None:
            return ("The scoreboard is frozen for final scoring; team "
                "names cannot change now.")
        if row is not None:
            return ("This team name is already taken. Pick another one, or "
                "ask an admin to release it.")
        db.execute("UPDATE entries SET team = ?, secret = ? WHERE guest = ?",
            (team, secret, guest))
    elif row is None:
        if final() is not None:
            # A team registering now would show up on the frozen standings
            # but not in the verified ranking, which scored the entries as
            # they were when the freeze started.
            return ("The scoreboard is frozen for final scoring; no new "
                "teams can join now.")
        db.execute("INSERT INTO entries (team, secret, guest, updated) "
            "VALUES (?, ?, ?, ?)", (team, secret, guest, now))
    elif secrets.compare_digest(secret.encode(), row[0].encode()):
        # Re-claim after logout/cull: rebind the entry to the new guest.
        db.execute("UPDATE entries SET guest = ? WHERE team = ?",
            (guest, team))
    else:
        return ("This team name is already taken. Pick another one, or "
            "ask an admin to release it.")
    db.commit()
    return None


def push(guest, score, source, svg):
    """
    Records a pushed build state (score None = checks failed) for the entry
    bound to guest; False if none.
    """
    now = time.strftime('%H:%M:%S')
    changed = db.execute("UPDATE entries SET score = ?, source = ?, "
        "svg = ?, updated = ? WHERE guest = ?",
        (score, source, svg, now, guest)).rowcount
    db.commit()
    return changed > 0


def valid_svg(svg):
    """
    Whether a pushed schematic is a well-formed SVG document. It is
    participant-controlled and later served on the hub's origin (as an
    image, which cannot script or load anything, and with the CSP below);
    this keeps garbage out of the database, it is not the security boundary.
    """
    if not (isinstance(svg, str) and 0 < len(svg) <= SVG_MAXLEN):
        return False
    try:
        root = ET.fromstring(svg)
    except ET.ParseError:
        return False
    return root.tag == '{http://www.w3.org/2000/svg}svg'


def final():
    """
    Final scoring state: None while the board is live, else a dict with
    'started' and 'result' (None = running, list = verified results as
    rescore.py returns them, dict = {'error': text}).
    """
    row = db.execute("SELECT started, result FROM final").fetchone()
    if row is None:
        return None
    return {'started': row[0],
        'result': None if row[1] is None else json.loads(row[1])}


def ranking(result):
    """rescore.py results ordered: ranked by verified current, then the rest."""
    return sorted(result,
        key=lambda r: (r['verified'] is None, r['verified'] or 0))


def final_public():
    """
    The final scoring state for participants (API and non-admin projector):
    the verified ranking with each failure cut to its first line. Full
    reasons (tracebacks may quote a submission) are for the admin view only.
    """
    state = final()
    if state is None or state['result'] is None:
        return state
    if isinstance(state['result'], dict):
        # The error text is for the admin (it describes the hub side).
        return {'started': state['started'], 'result': {'error': True}}
    return {'started': state['started'], 'result': [
        {'team': r['team'], 'verified': r['verified'],
            'fails': [f.splitlines()[0] for f in r['fails']]}
        for r in ranking(state['result'])]}


def run_rescore(entries):
    """
    Runs rescore.py --json over entries [(team, score, source)] in a
    throwaway container of the user image and returns its result list.
    Participant code executes in there, so the container gets the same
    isolation as a user container (Kata runtime, resource caps) and, unlike
    one, no network at all; the inputs go in and the result comes out
    through the docker API instead of mounts. Runs on a worker thread:
    must not touch db.
    """
    submissions = json.dumps([{'team': team, 'score': score, 'source': source}
        for team, score, source in entries]).encode()
    tar = io.BytesIO()
    with tarfile.open(fileobj=tar, mode='w') as archive:
        info = tarfile.TarInfo('rescore')
        info.type, info.mode = tarfile.DIRTYPE, 0o755
        archive.addfile(info)
        for name, data in (('rescore.py', RESCORE_SRC),
                ('submissions.json', submissions)):
            info = tarfile.TarInfo('rescore/' + name)
            info.size, info.mode = len(data), 0o644
            archive.addfile(info, io.BytesIO(data))
    client = docker.from_env()
    container = client.containers.create(IMAGE,
        ['python3', 'rescore/rescore.py', '--json', 'rescore/submissions.json'],
        working_dir=WORKDIR, network_mode='none', runtime=RUNTIME,
        mem_limit=MEM_LIMIT, nano_cpus=int(CPU_LIMIT * 1e9),
        tmpfs={'/tmp': 'size=256m'})
    try:
        container.put_archive(WORKDIR, tar.getvalue())
        container.start()
        try:
            status = container.wait(
                timeout=RESCORE_SETUP + RESCORE_TIMEOUT * len(entries))
        except (requests.exceptions.ReadTimeout,
                requests.exceptions.ConnectionError):
            # docker-py reports the timeout of the streaming wait as
            # either, depending on the version.
            container.kill()
            raise TimeoutError("final scoring container timed out")
        if status['StatusCode'] != 0:
            # A traceback on stderr is rescore.py's own failure; an empty
            # log means the process was killed (OOMKilled: the 2G memory
            # cap) or the sandbox itself failed (State.Error).
            container.reload()
            state = container.attrs.get('State', {})
            error = state.get('Error') or (status.get('Error') or {}).get(
                'Message', '')
            raise RuntimeError(
                f"rescore.py failed with exit status {status['StatusCode']}"
                + (" (killed: out of memory)" if state.get('OOMKilled')
                    else "")
                + (f": {error}" if error else "")
                + "\n" + container.logs(stdout=True, stderr=True).decode(
                    errors='replace')[-4000:])
        # rescore.py --json prints the result as the last line of stdout.
        stdout = container.logs(stdout=True, stderr=False).decode()
        return json.loads(stdout.splitlines()[-1])
    finally:
        container.remove(force=True)


def start_final():
    """
    Freezes the board and starts final scoring of the current entries in
    the background; no-op while a run is in progress. The result lands in
    the final row when the run ends, unless the row was deleted meanwhile
    (admin went back to live scores: the run's result is then dropped).
    """
    state = final()
    if state is not None and state['result'] is None:
        return
    entries = db.execute("SELECT team, score, source FROM entries").fetchall()
    started = time.strftime('%H:%M:%S')
    db.execute("INSERT OR REPLACE INTO final VALUES (1, ?, NULL)", (started,))
    db.commit()
    loop = ioloop.IOLoop.current()

    def done(future):
        try:
            result = future.result()
        except Exception:
            result = {'error': traceback.format_exc()}
        db.execute("UPDATE final SET result = ? "
            "WHERE result IS NULL AND started = ?",
            (json.dumps(result), started))
        db.commit()

    loop.add_future(loop.run_in_executor(None, run_rescore, entries), done)


def end_final():
    """Back to live scores: lifts the freeze and discards the results."""
    db.execute("DELETE FROM final")
    db.commit()


STYLE = """
    body { font-family: sans-serif; background: #f4f5f7; color: #111;
        margin: 0; padding: 2em 1em; }
    main { max-width: 56em; margin: 0 auto; }
    nav a { color: #06c; text-decoration: none; font-size: 0.95em; }
    nav a:hover { text-decoration: underline; }
    h1 { margin: 0.6em 0 0.2em; }
    .meta { color: #555; margin: 0 0 1.5em; }
    .meta a { color: #06c; }
    .card { background: #fff; border: 1px solid #ddd; border-radius: 0.5em;
        padding: 1em 1.5em; margin: 1em 0; overflow-x: auto; }
    .card h2 { font-size: 1em; margin: 0 0 0.8em; color: #555;
        text-transform: uppercase; letter-spacing: 0.05em; }
    .card img { display: block; max-width: 100%; margin: 0 auto; }
    .card pre { margin: 0; font-size: 0.9em; line-height: 1.4; }
    .noscore { color: #999; }
"""

SCORE_CELL = """{% if score is None %}
<td class="num noscore">no score</td>
{% else %}<td class="num">{{ '%.2f' % score }} µA</td>{% end %}"""

# One team's audit trail: the source and schematic pushed with its score.
# The audit view follows the pushed source, not the score: a build that
# failed a check stores source and schematic with a NULL score, and final
# scoring ranks such a team from that source (see rescore.py).
# The schematic is an <img>: SVG shown as an image cannot run scripts or
# load anything, whatever a participant put into it.
TEAM_PAGE = Template("""<!DOCTYPE html>
<html><head><title>{{ team }}</title>
<style>""" + STYLE + """</style></head>
<body><main>
<nav><a href="projector">&larr; Back to scoreboard</a></nav>
<h1>{{ team }}</h1>
{% if source is None %}
<p class="meta noscore">No build pushed yet.</p>
{% else %}
{% if score is None %}
<p class="meta noscore">No score: the latest build failed a check. Pushed
{{ updated }}.</p>
{% else %}
<p class="meta">Supply current {{ '%.2f' % score }} µA, pushed {{ updated }}</p>
{% end %}
{% if svg %}<section class="card"><h2>Schematic</h2>
<img src="schematic?id={{ id }}" alt="schematic"></section>{% end %}
<section class="card"><h2>Source</h2>
<pre>{{ source }}</pre></section>
{% end %}
</main></body></html>""")

# Team name cell of the leaderboard: a link to the team's page for admins
# (while the entry exists; a final ranking may name a deleted one).
TEAM_CELL = """{% set id = ids.get(team) %}
<td>{% if id is not None %}<a href="team?id={{ id }}">{{ team }}</a>{% else %}{{ team }}{% end %}</td>"""

# The small red X that asks (see .overlay) to delete an entry, admins only.
DELETE_CELL = """<td>{% if id is not None %}<a class="delete"
href="?delete={{ id }}" title="Delete entry">&#x2715;</a>{% end %}</td>"""

# Big type for the beamer; a plain server-rendered page that reloads itself,
# so it needs no script and re-authenticates through the hub by itself.
# When the viewer is an admin, the leaderboard links teams to their pages,
# shows the time of the last push and deletes entries, and the final scoring
# controls appear below it. Deletion is confirmed by a dialog the page
# renders itself (?delete=<id>): the CSP allows no script for a confirm().
PROJECTOR_PAGE = Template("""<!DOCTYPE html>
<html><head><title>Leaderboard</title>
<meta http-equiv="refresh" content="5">
<style>
    body { font-family: sans-serif; background: #fff; color: #111;
        margin: 5vh 10vw; }
    h1 { font-size: 5vh; margin: 0 0 3vh; }
    h1 .noscore { font-size: 3vh; font-weight: normal; }
    table { border-collapse: collapse; width: 100%; font-size: 4vh; }
    td, th { border-bottom: 0.4vh solid #ccc; padding: 1vh 2vh;
        text-align: left; }
    th { color: #555; font-size: 3vh; }
    .num { text-align: right; font-variant-numeric: tabular-nums; }
    .noscore { color: #999; }
    a { color: #06c; }
    a.delete { color: #c00; text-decoration: none; font-size: 2.5vh; }
    a.delete:hover { color: #f00; }
    td pre { margin: 0; font-size: 2vh; white-space: pre-wrap; }
    button { font: inherit; font-size: 2.2vh; padding: 1.2vh 3vh;
        border-radius: 0.8vh; border: 0.25vh solid #06c; background: #06c;
        color: #fff; cursor: pointer; }
    button:hover { background: #0052a3; border-color: #0052a3; }
    button.secondary { background: #fff; color: #06c; }
    button.secondary:hover { background: #eef4fb; }
    button.danger { background: #c00; border-color: #c00; }
    button.danger:hover { background: #a00; border-color: #a00; }
    .admin { display: flex; flex-wrap: wrap; align-items: center;
        gap: 2vh; margin-top: 4vh; font-size: 2.2vh; }
    .admin form { margin: 0; }
    .failure { flex-basis: 100%; background: #fff3f3; border: 0.25vh solid
        #f0c0c0; border-radius: 0.8vh; padding: 1.5vh 2.5vh; }
    .failure p { margin: 0 0 1vh; }
    .failure pre { margin: 0; white-space: pre-wrap; font-size: 2vh; }
    .overlay { position: fixed; inset: 0; background: rgba(0, 0, 0, 0.5);
        display: flex; align-items: center; justify-content: center; }
    .dialog { background: #fff; padding: 3vh 4vh; font-size: 2.5vh;
        max-width: 60vw; border-radius: 1vh; }
    .dialog p { margin: 0 0 3vh; }
    .dialog .actions { display: flex; gap: 2vh; }
    .dialog form { margin: 0; }
    .dialog button { font-size: 2.5vh; }
</style></head>
<body>
{% if final is not None and isinstance(final['result'], list) %}
<h1>Final ranking</h1>
<table><tr><th>#</th><th>Team</th><th class="num">Supply current</th>
{% if admin %}<th>Claimed</th><th>Not ranked because</th><th></th>{% end %}</tr>
{% for i, r in enumerate(final['result']) %}
{% if not r['fails'] %}
{% set score = r['verified'] %}{% set team = r['team'] %}
<tr><td class="num">{{ i + 1 }}</td>
""" + TEAM_CELL + SCORE_CELL + """
{% if admin %}{% set score = r.get('claimed') %}""" + SCORE_CELL + """
<td></td>""" + DELETE_CELL + """{% end %}
</tr>
{% end %}{% end %}
{% if admin %}{% for r in final['result'] %}{% if r['fails'] %}
{% set score = r.get('claimed') %}{% set team = r['team'] %}
<tr><td class="num">&ndash;</td>
""" + TEAM_CELL + """
<td class="num noscore">not ranked</td>
""" + SCORE_CELL + """
<td><pre>{{ '\\n'.join(r['fails']) }}</pre></td>
""" + DELETE_CELL + """</tr>
{% end %}{% end %}{% end %}
</table>
{% if not admin %}{% for r in final['result'] %}{% if r['fails'] %}
{% comment Outside the table: a <p> inside one would be foster-parented
above the leaderboard by the browser. %}
<p class="noscore">Not ranked: {{ r['team'] }} &ndash;
{{ '; '.join(r['fails']) }}</p>
{% end %}{% end %}{% end %}
{% else %}
<h1>Leaderboard{% if final is not None %}
<span class="noscore">(frozen for final scoring)</span>{% end %}</h1>
<table><tr><th>#</th><th>Team</th><th class="num">Supply current</th>
{% if admin %}<th>Updated</th><th></th>{% end %}</tr>
{% for i, (id, team, score, updated) in enumerate(rows) %}
<tr><td class="num">{{ i + 1 }}</td>
""" + TEAM_CELL + SCORE_CELL + """
{% if admin %}<td>{{ updated }}</td>""" + DELETE_CELL + """{% end %}</tr>
{% end %}</table>
{% end %}
{% if admin %}
<div class="admin">
{% if final is None %}
<form method="post">{% raw xsrf %}
<input type="hidden" name="action" value="final">
<button>Final scoring</button></form>
{% elif final['result'] is not None %}
{% if isinstance(final['result'], dict) %}
<div class="failure">
<p><b>Final scoring failed</b> (started {{ final['started'] }}).</p>
<pre>{{ final['result'].get('error', '') }}</pre>
</div>
{% end %}
<form method="post">{% raw xsrf %}
<input type="hidden" name="action" value="final">
<button>Run final scoring again</button></form>
<form method="post">{% raw xsrf %}
<input type="hidden" name="action" value="live">
<button class="secondary">Back to live scores</button></form>
{% end %}
</div>
{% if delete is not None %}
<div class="overlay"><div class="dialog">
<p>Delete the entry of team <b>{{ delete[1] }}</b>? This releases the
team name for a fresh claim.</p>
<div class="actions">
<form method="post">{% raw xsrf %}
<input type="hidden" name="action" value="delete">
<input type="hidden" name="id" value="{{ delete[0] }}">
<button class="danger">Delete</button></form>
<form method="get" action="projector">
<button class="secondary">Cancel</button></form>
</div></div></div>
{% end %}
{% end %}
</body></html>""")


class BaseHandler(HubOAuthenticated, web.RequestHandler):
    def set_default_headers(self):
        # No scripts, no external resources, on any page.
        # img-src for the pushed schematics on team pages.
        self.set_header('Content-Security-Policy',
            "default-src 'none'; style-src 'unsafe-inline'; "
            "img-src 'self'; form-action 'self'; base-uri 'none'")
        self.set_header('X-Content-Type-Options', 'nosniff')

    def require_admin(self):
        if not self.current_user.get('admin', False):
            raise web.HTTPError(403, "admin only")

    def entry_id(self, name='id', body=False):
        """The integer entry id in the named query (or body) argument."""
        get = self.get_body_argument if body else self.get_query_argument
        try:
            return int(get(name))
        except ValueError:
            raise web.HTTPError(400, "invalid entry id")


class ApiHandler(BaseHandler):
    """
    JSON endpoints for the frontend's Scoreboard client. Their first request
    from a fresh browser bootstraps the service's OAuth cookie: the GET is
    redirected through the hub's authorize endpoint and back, which fetch()
    follows within the same origin.
    """

    def check_xsrf_cookie(self):
        # The calling page (/user/<name>/app.html) cannot read this
        # service's path-scoped xsrf cookie, so same-origin is enforced from
        # the request headers instead. Both are set by the browser and
        # cannot be forged by a cross-site page: Origin decides whenever it
        # is present, and only where it is missing entirely (some browsers
        # and extensions strip it from same-origin POSTs) does
        # Sec-Fetch-Site decide. A cross-site request carries at least one
        # of the two saying so, and is rejected either way.
        origin = self.request.headers.get('Origin')
        site = self.request.headers.get('Sec-Fetch-Site')
        if origin:
            if urlparse(origin).netloc != self.request.host:
                raise web.HTTPError(403, "cross-origin request rejected")
        elif site not in ('same-origin', 'none'):
            # 'none' is what a direct navigation carries; 'same-site' is a
            # different host on the same site, which this service is not.
            if site:
                raise web.HTTPError(403, "cross-origin request rejected "
                    f"(Sec-Fetch-Site: {site})")
            raise web.HTTPError(403, "request without Origin and "
                "Sec-Fetch-Site headers rejected: the scoreboard cannot "
                "tell it apart from a cross-site request")

    def json_body(self):
        try:
            body = json.loads(self.request.body)
        except ValueError:
            raise web.HTTPError(400, "invalid JSON")
        if not isinstance(body, dict):
            raise web.HTTPError(400, "invalid JSON")
        return body

    def write_state(self):
        rows = [{'team': team, 'score': score, 'updated': updated}
            for _, team, score, updated in standings()]
        self.set_header('Cache-Control', 'no-store')
        self.finish({'team': team_of(self.current_user['name']),
            'rows': rows, 'final': final_public()})


class StateHandler(ApiHandler):
    @web.authenticated
    def get(self):
        self.write_state()


class ClaimHandler(ApiHandler):
    @web.authenticated
    def post(self):
        body = self.json_body()
        team = body.get('team')
        secret = body.get('secret')
        if not (isinstance(team, str) and isinstance(secret, str)):
            raise web.HTTPError(400, "invalid claim")
        team = team.strip()
        if not (1 <= len(team) <= TEAM_MAXLEN and team.isprintable()):
            error = f"Team name must be 1-{TEAM_MAXLEN} printable characters."
        elif not (1 <= len(secret) <= SECRET_MAXLEN and secret.isprintable()):
            raise web.HTTPError(400, "invalid claim")
        else:
            error = claim(team, secret, self.current_user['name'])
        if error:
            # Expected user-facing outcomes (name taken, ...) are answered
            # as data, not as HTTP errors: the frontend shows them inline.
            self.set_status(409)
            self.finish({'error': error})
        else:
            self.write_state()


class PushHandler(ApiHandler):
    @web.authenticated
    def post(self):
        body = self.json_body()
        try:
            score = body['score']
            source = body['source']
            svg = body.get('svg')
            if score is not None:
                score = float(score)
                if not 0 < score < 1e6:
                    raise ValueError
            if not (isinstance(source, str) and source.strip()
                    and len(source) <= SOURCE_MAXLEN):
                raise ValueError
            if svg is not None and not valid_svg(svg):
                raise ValueError
        except (ValueError, KeyError, TypeError):
            raise web.HTTPError(400, "invalid score push")
        if final() is not None:
            self.set_status(409)
            self.finish({'error': "The scoreboard is frozen for final scoring."})
            return
        if not push(self.current_user['name'], score, source, svg):
            raise web.HTTPError(404, "no team registered for this session")
        self.set_status(204)


class RootHandler(BaseHandler):
    @web.authenticated
    def get(self):
        # Teams never browse here (their scoreboard lives in the app); the
        # bare service URL is what someone types for the beamer.
        self.redirect(url_path_join(PREFIX, 'projector'))


class ProjectorHandler(BaseHandler):
    @web.authenticated
    def get(self):
        rows = standings()
        if self.current_user.get('admin', False):
            state = final()
            if state and isinstance(state['result'], list):
                state = {'started': state['started'],
                    'result': ranking(state['result'])}
            # ?delete=<id> asks to confirm deleting that entry (if it still
            # exists; the POST redirects to the bare page afterwards).
            delete = None
            if self.get_query_argument('delete', None) is not None:
                delete = db.execute("SELECT id, team FROM entries WHERE id = ?",
                    (self.entry_id('delete'),)).fetchone()
            self.finish(PROJECTOR_PAGE.generate(rows=rows, final=state,
                admin=True, ids={team: id for id, team, _, _ in rows},
                delete=delete, xsrf=self.xsrf_form_html()))
        else:
            self.finish(PROJECTOR_PAGE.generate(rows=rows,
                final=final_public(), admin=False, ids={}, delete=None,
                xsrf=''))

    @web.authenticated
    def post(self):
        self.require_admin()
        action = self.get_body_argument('action')
        if action == 'delete':
            db.execute("DELETE FROM entries WHERE id = ?",
                (self.entry_id(body=True),))
            db.commit()
        elif action == 'final':
            start_final()
        elif action == 'live':
            end_final()
        else:
            raise web.HTTPError(400, "unknown action")
        self.redirect(self.request.path)


class TeamHandler(BaseHandler):
    @web.authenticated
    def get(self):
        self.require_admin()
        id = self.entry_id()
        row = db.execute("SELECT team, score, source, svg, updated FROM entries "
            "WHERE id = ?", (id,)).fetchone()
        if row is None:
            raise web.HTTPError(404)
        team, score, source, svg, updated = row
        self.finish(TEAM_PAGE.generate(id=id, team=team, score=score,
            source=source, svg=svg, updated=updated))


class SchematicHandler(BaseHandler):
    @web.authenticated
    def get(self):
        self.require_admin()
        row = db.execute("SELECT svg FROM entries WHERE id = ?",
            (self.entry_id(),)).fetchone()
        if row is None or row[0] is None:
            raise web.HTTPError(404)
        # Served as an image (see TEAM_PAGE); nosniff keeps it one.
        self.set_header('Content-Type', 'image/svg+xml; charset=utf-8')
        self.finish(row[0])


def main():
    app = web.Application([
        (PREFIX, RootHandler),
        (url_path_join(PREFIX, 'api/state'), StateHandler),
        (url_path_join(PREFIX, 'api/claim'), ClaimHandler),
        (url_path_join(PREFIX, 'api/push'), PushHandler),
        (url_path_join(PREFIX, 'projector'), ProjectorHandler),
        (url_path_join(PREFIX, 'team'), TeamHandler),
        (url_path_join(PREFIX, 'schematic'), SchematicHandler),
        (url_path_join(PREFIX, 'oauth_callback'), HubOAuthCallbackHandler),
    ], cookie_secret=secrets.token_bytes(32), xsrf_cookies=True)
    url = urlparse(os.environ['JUPYTERHUB_SERVICE_URL'])
    app.listen(url.port, url.hostname)
    ioloop.IOLoop.current().start()


if __name__ == '__main__':
    main()
