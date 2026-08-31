# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
support/hub/scoreboard.py: the hub's scoreboard service. Covers the parts
that need no hub and no browser: team claiming, the rendered pages and the
same-origin check of the JSON API.
"""

import importlib.util
import sys
import types
from pathlib import Path

import pytest
from tornado import web

SCOREBOARD = Path(__file__).parent.parent / 'scoreboard.py'


def url_path_join(*pieces):
    """Minimal stand-in for jupyterhub.utils.url_path_join."""
    return '/' + '/'.join(p.strip('/') for p in pieces if p.strip('/'))


@pytest.fixture
def sb(tmp_path, monkeypatch):
    """
    The scoreboard service module with a private database. It is a hub-side
    script, not part of the ordec package, so it is loaded from its path,
    with stand-ins for the deployment-only imports (docker, jupyterhub) that
    the tested code paths never reach.
    """
    monkeypatch.setenv('JUPYTERHUB_SERVICE_PREFIX', '/services/scoreboard/')
    monkeypatch.setenv('ORDEC_SCOREBOARD_DB', str(tmp_path / 'scoreboard.sqlite'))
    auth = types.ModuleType('jupyterhub.services.auth')
    auth.HubOAuthenticated = type('HubOAuthenticated', (), {})
    auth.HubOAuthCallbackHandler = type('HubOAuthCallbackHandler', (), {})
    utils = types.ModuleType('jupyterhub.utils')
    utils.url_path_join = url_path_join
    services = types.ModuleType('jupyterhub.services')
    services.auth = auth
    jupyterhub = types.ModuleType('jupyterhub')
    jupyterhub.services = services
    jupyterhub.utils = utils
    for name, module in (('docker', types.ModuleType('docker')),
            ('jupyterhub', jupyterhub),
            ('jupyterhub.services', services),
            ('jupyterhub.services.auth', auth),
            ('jupyterhub.utils', utils)):
        monkeypatch.setitem(sys.modules, name, module)
    spec = importlib.util.spec_from_file_location('scoreboard', SCOREBOARD)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    yield module
    module.db.close()


def freeze(sb, result=None):
    """Puts the board into final scoring (result NULL = run in progress)."""
    sb.db.execute("INSERT OR REPLACE INTO final VALUES (1, '11:00:00', ?)",
        (result,))
    sb.db.commit()


def test_claim_while_frozen(sb):
    assert sb.claim('early', 'secret1', 'guest1') is None
    freeze(sb)
    assert sb.final() is not None

    # A new entry would appear on the frozen standings but not in the
    # verified ranking, which scored the entries as they were:
    error = sb.claim('late', 'secret2', 'guest2')
    assert error is not None and 'frozen' in error
    assert sb.team_of('guest2') is None

    # Re-claiming an existing entry stays allowed (the browser comes back
    # as a new guest after an idle cull) ...
    assert sb.claim('early', 'secret1', 'guest1b') is None
    assert sb.team_of('guest1b') == 'early'
    # ... but renaming it does not.
    error = sb.claim('renamed', 'secret1', 'guest1b')
    assert error is not None and 'frozen' in error
    assert sb.team_of('guest1b') == 'early'


def test_team_page_follows_the_pushed_source(sb):
    # A failed check pushes source and schematic with a NULL score; final
    # scoring ranks that source, so the audit view must show it.
    page = sb.TEAM_PAGE.generate(id=1, team='shy', score=None,
        source='cell Amp {}', svg='<svg/>', updated='10:00:00').decode()
    assert 'cell Amp {}' in page
    assert 'schematic?id=1' in page
    assert 'failed a check' in page

    page = sb.TEAM_PAGE.generate(id=2, team='ranked', score=12.5,
        source='cell Amp {}', svg='<svg/>', updated='10:00:00').decode()
    assert 'cell Amp {}' in page
    assert 'Supply current 12.50' in page

    # A team that registered but never pushed has nothing to show.
    page = sb.TEAM_PAGE.generate(id=3, team='lurker', score=None,
        source=None, svg=None, updated='10:00:00').decode()
    assert 'No build pushed yet' in page
    assert 'schematic?id=' not in page


def test_projector_not_ranked_outside_the_table(sb):
    # <p> elements inside a <table> are foster-parented above it by the
    # browser, which would detach the notices from the leaderboard.
    final = {'started': '11:00:00', 'result': [
        {'team': 'a', 'verified': 30.0, 'fails': []},
        {'team': 'b', 'verified': None, 'fails': ['gain 3.00 < 20 at tt']}]}
    page = sb.PROJECTOR_PAGE.generate(rows=[], final=final, admin=False,
        ids={}, delete=None, xsrf='').decode()
    assert page.index('</table>') < page.index('Not ranked: b')

    # The admin variant lists them as table rows instead.
    page = sb.PROJECTOR_PAGE.generate(rows=[], final=final, admin=True,
        ids={'a': 1, 'b': 2}, delete=None, xsrf='').decode()
    assert 'Not ranked:' not in page
    assert page.index('gain 3.00 &lt; 20 at tt') < page.index('</table>')


def check_xsrf(sb, headers, host='hub.example'):
    request = types.SimpleNamespace(headers=headers, host=host)
    sb.ApiHandler.check_xsrf_cookie(types.SimpleNamespace(request=request))


def test_xsrf_origin(sb):
    check_xsrf(sb, {'Origin': 'https://hub.example'})
    with pytest.raises(web.HTTPError):
        check_xsrf(sb, {'Origin': 'https://evil.example'})
    # A present Origin decides on its own, whatever the metadata says:
    with pytest.raises(web.HTTPError):
        check_xsrf(sb, {'Origin': 'https://evil.example',
            'Sec-Fetch-Site': 'same-origin'})


def test_xsrf_without_origin(sb):
    # Browsers (and extensions) that strip Origin from same-origin POSTs
    # are accepted on the strength of the fetch metadata instead.
    check_xsrf(sb, {'Sec-Fetch-Site': 'same-origin'})
    check_xsrf(sb, {'Sec-Fetch-Site': 'none'})
    for site in ('cross-site', 'same-site'):
        with pytest.raises(web.HTTPError):
            check_xsrf(sb, {'Sec-Fetch-Site': site})

    # Neither header: still refused, but recognizably so.
    with pytest.raises(web.HTTPError) as excinfo:
        check_xsrf(sb, {})
    assert 'Sec-Fetch-Site' in excinfo.value.log_message
