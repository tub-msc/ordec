// SPDX-FileCopyrightText: 2025 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

import * as d3 from "d3";
import { SimPlot } from './simplot.js';
import renderMathInElement from 'katex/contrib/auto-render';
import 'katex/dist/katex.min.css';

function simpleReportElementClass(renderNode) {
    return class {
        constructor(container) {
            this.container = container;
        }

        update(msgData) {
            this.container.replaceChildren(renderNode(msgData));
        }
    };
}

// Appends plain text to el, turning `...` spans into inline code elements.
// PassFail instructions and hints are plain text rather than markdown, but
// backticks around pin, net and instance names make them far easier to read.
// Built from text nodes, so the text is never interpreted as HTML.
function appendTextWithCode(el, text) {
    text.split('`').forEach((part, i) => {
        if (i % 2) {
            const code = document.createElement('code');
            code.innerText = part;
            el.appendChild(code);
        } else if (part) {
            el.appendChild(document.createTextNode(part));
        }
    });
}

export const Markdown = simpleReportElementClass((msgData) => {
    const section = document.createElement('div');
    section.classList.add('report-markdown');
    section.innerHTML = msgData.html;
    // TeX math spans; the backend keeps them out of markdown2's hands
    // (see schema.py Markdown.element_webdata).
    renderMathInElement(section, {
        delimiters: [
            {left: '$$', right: '$$', display: true},
            {left: '$', right: '$', display: false},
        ],
        throwOnError: false,
    });
    return section;
});

export const Html = simpleReportElementClass((msgData) => {
    const section = document.createElement('div');
    section.classList.add('report-html');
    section.innerHTML = msgData.html;
    return section;
});

export const PreformattedText = simpleReportElementClass((msgData) => {
    const pre = document.createElement('pre');
    pre.classList.add('report-preformatted');
    pre.innerText = msgData.text;
    return pre;
});

export const Svg = simpleReportElementClass((msgData) => {
    const svg = d3.create("svg")
        .attr("class", "report-svg")
        .attr("viewBox", msgData.viewbox);
    svg.attr("width", msgData.width);
    svg.attr("height", msgData.height);
    svg.append("g").html(msgData.inner);
    return svg.node();
});

// Stateful class (not simpleReportElementClass) so that hint visibility
// survives report re-renders (renderer instances are reused by index).
export class PassFail {
    constructor(container) {
        this.container = container;
        this.hintVisible = false;
    }

    update(msgData) {
        const root = document.createElement('div');
        root.classList.add('report-passfail');
        root.classList.add(msgData.passed
            ? 'report-passfail-pass' : 'report-passfail-fail');

        const head = document.createElement('div');
        head.classList.add('report-passfail-head');

        const badge = document.createElement('span');
        badge.classList.add('report-passfail-badge');
        badge.innerText = msgData.passed ? 'PASS' : 'FAIL';
        head.appendChild(badge);

        const label = document.createElement('span');
        label.classList.add('report-passfail-label');
        label.innerText = msgData.label;
        head.appendChild(label);

        root.appendChild(head);

        // A passing check is collapsed to badge + label; instructions
        // and hint only matter while the check fails.
        if (!msgData.passed) {
            if (msgData.instructions) {
                const instructions = document.createElement('div');
                instructions.classList.add('report-passfail-instructions');
                appendTextWithCode(instructions, msgData.instructions);
                root.appendChild(instructions);
            }

            if (msgData.hint) {
                const hintBtn = document.createElement('button');
                hintBtn.classList.add('report-passfail-hintbtn');
                const hint = document.createElement('div');
                hint.classList.add('report-passfail-hint');
                appendTextWithCode(hint, msgData.hint);
                const applyHintVisibility = () => {
                    hint.style.display = this.hintVisible ? '' : 'none';
                    hintBtn.innerText = this.hintVisible
                        ? 'Hide hint' : 'Show hint';
                };
                hintBtn.onclick = () => {
                    this.hintVisible = !this.hintVisible;
                    applyHintVisibility();
                };
                applyHintVisibility();
                head.appendChild(hintBtn);
                root.appendChild(hint);
            }
        }

        this.container.replaceChildren(root);
    }
}

export class Plot2d {
    constructor(container, reportContext) {
        this.container = container;
        this.reportContext = reportContext;
        this.plot = null;
        this.savedHidden = null;
        this.savedZoom = null;
    }

    update(msgData) {
        if (this.plot) {
            this.savedHidden = this.plot.getHiddenNames();
            this.savedZoom = this.plot.getZoomState();
        }
        this.destroy();

        const root = document.createElement('div');
        root.classList.add('report-plot2d');
        this.container.replaceChildren(root);

        this.plot = new SimPlot(root, {
            xlabel: msgData.xlabel,
            ylabel: msgData.ylabel,
            xscale: msgData.xscale,
            yscale: msgData.yscale,
            fixedHeight: msgData.height,
        });

        this.plot.setData(msgData.x, msgData.series);
        if (this.savedHidden) {
            this.plot.setHiddenNames(this.savedHidden);
        }
        if (this.savedZoom) {
            this.plot.setZoomState(this.savedZoom);
        }
        if (this.reportContext) {
            this.reportContext.plotGroups.register(
                this.plot,
                msgData.group
            );
        }
    }

    destroy() {
        if (!this.plot) return;
        if (this.reportContext) {
            this.reportContext.plotGroups.unregister(this.plot);
        }
        this.plot.destroy();
        this.plot = null;
    }
}
