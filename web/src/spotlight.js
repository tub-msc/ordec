// SPDX-FileCopyrightText: 2026 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

// Minimal spotlight tour: dims the whole page and highlights one target
// (or a group of adjacent targets) at a time, with a caption and
// Back/Skip/Next buttons. Used by course mode for the intro tour of the
// very first lesson (see CourseController.startTour).

export class Spotlight {
    // steps: [{target: () => Element|Element[]|null, title, text}]. A step's
    // target may return several elements; they are highlighted with one
    // cutout spanning all of them. Steps whose targets do not (or no longer)
    // exist are skipped. onDone fires when the tour ends, via Skip, via
    // Done, or because no valid step is left.
    constructor(steps, onDone) {
        this.steps = steps;
        this.onDone = onDone;
        this.index = -1;
        this.targets = [];
        this.onResize = () => this.position();
    }

    start() {
        this.root = document.createElement('div');
        this.root.className = 'spotlight';
        this.root.innerHTML = `
            <div class="spotlight-cutout"></div>
            <div class="spotlight-caption">
                <strong class="spotlight-title"></strong>
                <p class="spotlight-text"></p>
                <div class="spotlight-buttons">
                    <span class="spotlight-counter"></span>
                    <button class="toolbar-btn spotlight-skip">Skip tour</button>
                    <button class="toolbar-btn spotlight-back">Back</button>
                    <button class="toolbar-btn spotlight-next">Next</button>
                </div>
            </div>
        `;
        this.root.querySelector('.spotlight-skip').onclick = () => this.finish();
        this.root.querySelector('.spotlight-back').onclick = () => this.back();
        this.root.querySelector('.spotlight-next').onclick = () => this.next();
        document.body.appendChild(this.root);
        window.addEventListener('resize', this.onResize);
        this.next();
    }

    // Connected target elements of step i (empty for invalid steps).
    stepTargets(i) {
        let targets = this.steps[i].target();
        if (!targets) {
            return [];
        }
        if (!Array.isArray(targets)) {
            targets = [targets];
        }
        return targets.filter(el => el && el.isConnected);
    }

    // Index of the next/previous step with an existing target, or -1.
    nextValidStep(from) {
        for (let i = from; i < this.steps.length; i++) {
            if (this.stepTargets(i).length) {
                return i;
            }
        }
        return -1;
    }

    prevValidStep(from) {
        for (let i = from; i >= 0; i--) {
            if (this.stepTargets(i).length) {
                return i;
            }
        }
        return -1;
    }

    next() {
        const i = this.nextValidStep(this.index + 1);
        if (i < 0) {
            this.finish();
            return;
        }
        this.show(i);
    }

    back() {
        const i = this.prevValidStep(this.index - 1);
        if (i >= 0) {
            this.show(i);
        }
    }

    show(i) {
        this.index = i;
        const step = this.steps[i];
        this.targets = this.stepTargets(i);
        this.root.querySelector('.spotlight-title').innerText = step.title;
        this.root.querySelector('.spotlight-text').innerText = step.text;
        this.root.querySelector('.spotlight-counter').innerText =
            (i + 1) + '/' + this.steps.length;
        this.root.querySelector('.spotlight-back').disabled =
            (this.prevValidStep(i - 1) < 0);
        this.root.querySelector('.spotlight-next').innerText =
            (this.nextValidStep(i + 1) < 0) ? 'Done' : 'Next';
        this.position();
    }

    position() {
        if (!this.root) {
            return;
        }
        const targets = this.targets.filter(el => el.isConnected);
        if (!targets.length) {
            return;
        }
        // One cutout spanning the union of all target rectangles.
        const r = targets.map(el => el.getBoundingClientRect()).reduce(
            (a, b) => ({
                left: Math.min(a.left, b.left),
                top: Math.min(a.top, b.top),
                right: Math.max(a.right, b.right),
                bottom: Math.max(a.bottom, b.bottom),
            }));
        const pad = 6;
        const cutout = this.root.querySelector('.spotlight-cutout');
        cutout.style.left = (r.left - pad) + 'px';
        cutout.style.top = (r.top - pad) + 'px';
        cutout.style.width = (r.right - r.left + 2 * pad) + 'px';
        cutout.style.height = (r.bottom - r.top + 2 * pad) + 'px';

        // Caption below the cutout, or above it when there is no room. For
        // tall targets (e.g. a whole result viewer) neither fits, so it goes
        // beside the cutout instead, vertically centered - preferring the
        // left side - rather than covering the highlighted element.
        const caption = this.root.querySelector('.spotlight-caption');
        const capW = caption.offsetWidth;
        const capH = caption.offsetHeight;
        const clampLeft = (left) => Math.max(8,
            Math.min(left, window.innerWidth - capW - 8));
        let left = clampLeft(r.left - pad);
        let top = r.bottom + pad + 12;
        if (top + capH > window.innerHeight - 8) {
            top = r.top - pad - capH - 12;
        }
        if (top < 8) {
            top = Math.max(8, Math.min((r.top + r.bottom - capH) / 2,
                window.innerHeight - capH - 8));
            if (r.left - pad - capW - 12 >= 8) {
                left = r.left - pad - capW - 12;
            } else if (r.right + pad + capW + 12 <= window.innerWidth - 8) {
                left = r.right + pad + 12;
            }
            // Otherwise the target spans the full width too; keep the
            // clamped default and accept the overlap.
        }
        caption.style.left = left + 'px';
        caption.style.top = Math.max(8, top) + 'px';
    }

    // Removes the overlay without reporting the tour as done. Used when the
    // tour is cancelled from outside, e.g. by a course lesson switch that
    // replaces the panels the steps point at. Returns whether a running tour
    // was actually cancelled, so that calling it twice is harmless.
    cancel() {
        if (!this.root) {
            return false;
        }
        window.removeEventListener('resize', this.onResize);
        this.root.remove();
        this.root = null;
        this.targets = [];
        return true;
    }

    finish() {
        if (this.cancel() && this.onDone) {
            this.onDone();
        }
    }
}
