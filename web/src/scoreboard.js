// SPDX-FileCopyrightText: 2026 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

// Scoreboard client of competition courses ("competition": true in
// course.json, see course.js), talking to the hub's scoreboard service
// (support/hub/scoreboard.py) at session.scoreboardUrl:
//   - join(): the team dialog shown before the course opens. Claims a team
//     name for this session, or silently re-claims the one kept in
//     localStorage (after an idle cull, the browser comes back as a new hub
//     guest and has to re-bind its team).
//   - push(): the state after a build: the score (null when checks fail)
//     plus the source that produced it and its schematic as SVG. Held back
//     while the board is frozen for final scoring (state.final != null) and
//     re-sent once it is live again.
//   - ScoreboardPanel: GoldenLayout component polling the standings, or
//     the verified final ranking once the admin ran final scoring. Shows
//     a spinner on the own score while it is out of date (rebuild or push
//     in progress) and offers to rename the team.

import { getCourseController, suppressCloseControls } from './course.js';

const POLL_INTERVAL = 3000; // ms between standings polls

function newSecret() {
    const bytes = new Uint8Array(16);
    window.crypto.getRandomValues(bytes);
    return Array.from(bytes, b => b.toString(16).padStart(2, '0')).join('');
}

export class Scoreboard {
    constructor(url, course) {
        this.url = url; // service base URL, ends with '/'
        this.course = course;
        this.storageKey = 'ordecTeam:' + course.name;
        this.team = null; // team name bound to this session, once joined
        this.lastPush = null; // {score, source, svg} of the last successful push
        // Payload of a push that could not be sent (board frozen, or the
        // entry was gone); re-sent once pushing is possible again.
        this.pendingPush = null;
        this.frozen = false; // final scoring in progress or done: no pushes
        this.pushing = false; // a push request is in flight
        this.rejoining = false; // a recovery join is running
        this.panel = null; // the ScoreboardPanel, while one exists
    }

    // The own score on the board is out of date while a rebuild runs (the
    // course status is 'busy') or a push is in flight.
    stale() {
        const course = getCourseController();
        return !this.frozen && (this.pushing
            || (course !== null && course.reportStatus === 'busy'));
    }

    // Called by the course controller on status changes and by push().
    statusChanged() {
        this.panel?.renderStale();
    }

    // -- Service API ------------------------------------------------------

    // GET (body undefined) or JSON POST against the service. A fresh
    // browser's first request is redirected through the hub's OAuth
    // authorize endpoint and back, which sets the service's cookie; fetch()
    // follows that chain within the origin. Resolves to the parsed JSON
    // (null for 204); rejects with a user-facing message otherwise.
    async request(path, body) {
        let resp;
        try {
            resp = await fetch(this.url + path, body === undefined ? {} : {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(body),
            });
        } catch (e) {
            throw new Error('Could not reach the scoreboard (' + e.message + ').');
        }
        if (resp.status === 204) {
            return null;
        }
        let data = null;
        try {
            data = await resp.json();
        } catch (e) {
            // Tornado answers HTTPErrors with an HTML error page.
            const error = new Error('Unexpected answer from the scoreboard '
                + '(HTTP ' + resp.status + ').');
            error.status = resp.status;
            throw error;
        }
        if (!resp.ok) {
            const error = new Error(data.error || ('Scoreboard error (HTTP '
                + resp.status + ').'));
            // Callers distinguish outcomes by status (404: this session has
            // no entry any more, see push()).
            error.status = resp.status;
            throw error;
        }
        return data;
    }

    // {team, rows, final}: the team bound to this session (or null), the
    // standings (ranked first) and the final scoring state: null while the
    // board is live, else {started, result} with result null while it runs
    // (then with {done, total} rescoring progress), a list of
    // {team, verified} when done, or {error}.
    async fetchState() {
        const state = await this.request('api/state');
        const wasFrozen = this.frozen;
        this.frozen = state.final !== null;
        if (wasFrozen && !this.frozen) {
            // "Back to live scores": send what the freeze suppressed, so
            // the board does not stay stale for this team.
            this.flushPending();
        }
        if (this.team !== null && state.team === null) {
            // An admin deleted this session's entry; rejoin instead of
            // dropping every later score silently.
            this.recoverTeam();
        }
        return state;
    }

    // Pushes a score (null when the checks fail) with its source and
    // schematic (SVG markup or null) as audit trail. Deduplicated against
    // the last successful push; a failed push retries on the next report
    // refresh.
    push(score, source, svg) {
        const payload = {score: score, source: source, svg: svg};
        if (this.frozen) {
            // The service would refuse it (409); remember it for the
            // transition back to live scores.
            this.pendingPush = payload;
            return;
        }
        if (this.lastPush && this.lastPush.score === score
                && this.lastPush.source === source) {
            return;
        }
        this.lastPush = payload;
        this.pushing = true;
        this.statusChanged();
        this.request('api/push', payload)
        .then(() => {
            // Show the new score right away rather than at the next poll;
            // the own score counts as stale until it is on screen.
            return this.panel?.refresh();
        }).catch((e) => {
            console.error('scoreboard push failed:', e);
            this.lastPush = null;
            if (e.status === 404) {
                // The service has no entry for this session any more (an
                // admin deleted it): rejoin and re-send this build.
                this.pendingPush = payload;
                this.recoverTeam();
            }
        }).finally(() => {
            this.pushing = false;
            this.statusChanged();
        });
    }

    // Re-sends the push that was suppressed while the board was frozen or
    // while this session had no entry, once pushing is possible again.
    flushPending() {
        const pending = this.pendingPush;
        this.pendingPush = null;
        if (pending) {
            this.push(pending.score, pending.source, pending.svg);
        }
    }

    // Drops the stale team binding and runs the join flow again (silent
    // re-claim with the stored name and secret, or the dialog), then
    // re-sends the pending build. One at a time.
    async recoverTeam() {
        if (this.rejoining) {
            return;
        }
        this.rejoining = true;
        this.team = null;
        this.lastPush = null;
        try {
            await this.join();
        } catch (e) {
            console.error('scoreboard rejoin failed:', e);
        } finally {
            this.rejoining = false;
        }
        if (this.team !== null) {
            this.flushPending();
        }
    }

    // -- Team registration ------------------------------------------------

    loadStored() {
        try {
            const stored = JSON.parse(localStorage.getItem(this.storageKey));
            if (stored && typeof stored.name === 'string'
                    && typeof stored.secret === 'string') {
                return stored;
            }
        } catch (e) {
            console.error('Failed to parse stored team, ignoring:', e);
        }
        return null;
    }

    // Resolves once this session is bound to a team: right away when the
    // service already knows this session, after a silent re-claim with the
    // stored name and secret, or after the user picked a name in the dialog.
    async join() {
        const stored = this.loadStored();
        let error = null;
        try {
            let state = await this.fetchState();
            if (state.team === null && stored) {
                state = await this.request('api/claim',
                    {team: stored.name, secret: stored.secret});
            }
            if (state.team !== null) {
                this.team = state.team;
                return;
            }
        } catch (e) {
            error = e.message;
        }
        await this.showDialog(stored, error);
    }

    // Modal team dialog; resolves once a claim succeeded. stored is the
    // localStorage entry (name prefilled, secret reused for that name) and
    // error the message of a failed silent re-claim, if any. With rename
    // set, the dialog renames the team this session already holds and can
    // be cancelled (resolving without a claim).
    showDialog(stored, error, rename = false) {
        return new Promise((resolve) => {
            const overlay = document.createElement('div');
            overlay.id = 'teamdialog';
            overlay.innerHTML = `
                <form class="teamdialog-box">
                    <h2></h2>
                    <p>Pick a name for your team. Your score appears on the
                    scoreboard automatically whenever all checks of the task
                    pass; the lowest supply current wins.</p>
                    <label>Team name
                        <input class="teamdialog-name" maxlength="24" autocomplete="off" required>
                    </label>
                    <p class="teamdialog-error"></p>
                    <button class="teamdialog-join">Join</button>
                    <button type="button" class="teamdialog-cancel">Cancel</button>
                </form>`;
            overlay.querySelector('h2').textContent = this.course.title;
            const form = overlay.querySelector('form');
            const input = overlay.querySelector('.teamdialog-name');
            const errorEl = overlay.querySelector('.teamdialog-error');
            const button = overlay.querySelector('.teamdialog-join');
            const cancel = overlay.querySelector('.teamdialog-cancel');
            input.value = stored ? stored.name : '';
            errorEl.textContent = error || '';
            if (rename) {
                overlay.querySelector('p').textContent =
                    'Pick a new name for your team. Your score stays.';
                button.textContent = 'Rename';
                cancel.onclick = () => {
                    overlay.remove();
                    resolve();
                };
            } else {
                cancel.remove();
            }
            form.onsubmit = async (ev) => {
                ev.preventDefault();
                const name = input.value.trim();
                if (!name) {
                    return;
                }
                // Keep the secret of a name this browser already claimed
                // before (a re-claim after a transient failure); a new name
                // gets a fresh one.
                const secret = (stored && stored.name === name)
                    ? stored.secret : newSecret();
                button.disabled = true;
                try {
                    const state = await this.request('api/claim',
                        {team: name, secret: secret});
                    localStorage.setItem(this.storageKey,
                        JSON.stringify({name: name, secret: secret}));
                    this.team = state.team;
                } catch (e) {
                    errorEl.textContent = e.message;
                    button.disabled = false;
                    return;
                }
                overlay.remove();
                resolve();
            };
            document.body.appendChild(overlay);
            input.focus();
        });
    }
}

// The Scoreboard panel: live standings, polled from the service while the
// panel exists. Part of the competition course's shipped layout
// (challenge.uistate.json), movable but not closable like the Course panel.
export class ScoreboardPanel {
    constructor(container, state) {
        container.setTitle('Scoreboard');
        suppressCloseControls(container);
        this.element = document.createElement('div');
        this.element.className = 'scoreboard';
        container.element.appendChild(this.element);

        this.scoreboard = getCourseController()?.scoreboard || null;
        if (!this.scoreboard) {
            // The course is reachable by URL on servers without a scoreboard
            // (see landing-page.js); the panel then just says so.
            this.element.innerHTML = '<p class="scoreboard-error">'
                + 'The scoreboard is not available on this server.</p>';
            return;
        }
        this.released = false;
        this.timer = null;
        this.scoreboard.panel = this;
        container.addEventListener('beforeComponentRelease', () => {
            this.released = true;
            this.scoreboard.panel = null;
            window.clearTimeout(this.timer);
        });
        this.poll();
    }

    // Toggles the spinner on the own score (see .scoreboard-stale); the
    // tab title stays as it is.
    renderStale() {
        this.element.classList.toggle('scoreboard-stale',
            this.scoreboard.stale());
    }

    async refresh() {
        try {
            this.render(await this.scoreboard.fetchState());
        } catch (e) {
            this.element.innerHTML = '<p class="scoreboard-error"></p>';
            this.element.firstChild.textContent = e.message;
        }
    }

    // One poll at a time: the next one is scheduled once this one answered.
    async poll() {
        await this.refresh();
        if (!this.released) {
            this.timer = window.setTimeout(() => this.poll(), POLL_INTERVAL);
        }
    }

    render(state) {
        const finalDone = state.final !== null
            && Array.isArray(state.final.result);
        const children = [];
        if (state.final !== null) {
            const p = document.createElement('p');
            p.className = 'scoreboard-final';
            p.textContent = finalDone
                ? 'Final ranking, verified against the pristine testbench.'
                : 'Scores are frozen for final scoring.';
            if (state.final.result === null && state.final.progress) {
                // Rescoring progress; done stays 0 (indeterminate bar)
                // while the scoring container is still starting up.
                const prog = state.final.progress;
                const bar = document.createElement('progress');
                bar.max = prog.total;
                if (prog.done > 0) {
                    bar.value = prog.done;
                    p.append(' ', bar, ' ' + prog.done + '/' + prog.total);
                } else {
                    p.append(' ', bar);
                }
            }
            children.push(p);
        }
        const table = document.createElement('table');
        table.innerHTML = finalDone
            ? '<tr><th class="num">#</th><th>Team</th>'
                + '<th class="num">Supply current</th></tr>'
            : '<tr><th class="num">#</th><th>Team</th>'
                + '<th class="num">Supply current</th><th>Updated</th></tr>';
        const rows = finalDone ? state.final.result : state.rows;
        rows.forEach((row, i) => {
            const tr = document.createElement('tr');
            if (row.team === state.team) {
                tr.className = 'scoreboard-own';
            }
            // Final rows carry verified (null = not ranked; the reasons
            // are not public), live rows score/updated.
            const score = finalDone ? row.verified : row.score;
            const cells = finalDone
                ? [(score === null) ? '–' : String(i + 1), row.team,
                    (score === null) ? 'not ranked' : score.toFixed(2) + ' µA']
                : [String(i + 1), row.team,
                    (score === null) ? 'no score' : score.toFixed(2) + ' µA',
                    row.updated];
            const own = row.team === state.team && state.final === null;
            cells.forEach((text, j) => {
                const td = document.createElement('td');
                td.textContent = text;
                if (j === 0 || j === 2) {
                    td.className = 'num';
                }
                if (j === 2 && score === null) {
                    td.classList.add('noscore');
                }
                if (j === 1 && own) {
                    const rename = document.createElement('a');
                    rename.href = '#';
                    rename.className = 'scoreboard-rename';
                    rename.textContent = 'rename';
                    rename.onclick = (ev) => {
                        ev.preventDefault();
                        this.scoreboard.showDialog(
                            this.scoreboard.loadStored(), null, true)
                            .then(() => this.refresh());
                    };
                    td.append(' ', rename);
                }
                if (j === 2 && own) {
                    const spinner = document.createElement('span');
                    spinner.className = 'refresh-spinner scoreboard-spinner';
                    td.appendChild(spinner);
                }
                tr.appendChild(td);
            });
            table.appendChild(tr);
        });
        children.push(table);
        this.element.replaceChildren(...children);
        this.renderStale();
    }
}
