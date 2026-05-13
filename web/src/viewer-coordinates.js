// SPDX-FileCopyrightText: 2026 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

const EMPTY_COORDINATES = 'x=-  y=-';

export class CoordinateDisplay {
    constructor({ tagName = 'span', classNames = [] } = {}) {
        this.element = document.createElement(tagName);
        this.element.classList.add('viewer-coordinates', ...classNames);
        this.clear();
    }

    clear() {
        this.element.textContent = EMPTY_COORDINATES;
    }

    set(x, y) {
        this.element.textContent = `x=${x}  y=${y}`;
    }
}
