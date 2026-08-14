// SPDX-FileCopyrightText: 2025 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

import { viewEventBus } from '../event-bus.js';
import { View } from './view.js';

const TYPE_ORDER = ['pin', 'net', 'device', 'subcircuit'];
const TYPE_LABELS = {
    pin: 'Pins', net: 'Nets', device: 'Devices', subcircuit: 'Subcircuits',
};
const TYPE_ICONS = { pin: '⇔', net: '↑', device: '▱', subcircuit: '□' };
const ARROW_BOTH = '↔';
const ARROW_COLLAPSED = '▶';

function textSpan(text) {
    const span = document.createElement('span');
    span.textContent = text;
    return span;
}

function toggleSpan() {
    const span = textSpan(ARROW_COLLAPSED);
    span.className = 'lvs-toggle';
    return span;
}

// LVS Report viewer.
//
// Event bus protocol:
//   lvs:layout-select {pos, layoutView, layoutWireHash} - sent when item with layout_pos selected
//   lvs:schem-select {schem_nid, item_type, schemView, schemWireHash} - sent when item with schem_nid selected
//   lvs:clear - sent on deselect or destroy
//   lvs:request-open-views {layoutView, schemView, layoutWireHash, schemWireHash} - requests new viewer panels
//
// Pending mechanism: setPending('lvs:select', payload) stores selection for
// viewers opened later. Layout/schematic viewers call getPending on init.
//
// View naming: for the top-level circuit pair, layoutView/schemView use
// "<viewName>.ref_layout" and "<viewName>.ref_schematic", matching
// LvsReport SubgraphRef attributes. Circuit rows and item selections of
// subcircuit pairs use the per-pair views
// "<viewName>.subgraph.cursor_at(<nid>).ref_layout|ref_schematic",
// addressing the LvsCircuitPair node by nid. Every select payload
// carries its target views plus their subgraph wire hashes
// (layoutWireHash/schemWireHash), so only the viewers showing those views
// highlight - matched by name, or by hash for a viewer showing the
// same subgraph under a different view name: nids/positions are only
// meaningful in the pair's own subgraphs, and an untargeted broadcast
// would paint them into unrelated layout/schematic views.
export class LvsReport extends View {
    constructor(resContent, viewName, resultViewer, panelContainer) {
        super(resContent, viewName, resultViewer, panelContainer);
        this.el = document.createElement('div');
        this.el.className = 'lvs-viewer';
        this.selectedItemNid = null;
        resContent.appendChild(this.el);
    }

    update(data, wireHash) {
        const circuitMap = new Map();
        data.circuits.forEach(circuit => {
            circuitMap.set(circuit.nid, { ...circuit, itemsByType: { pin: [], net: [], device: [], subcircuit: [] } });
        });

        const itemMap = new Map();
        data.items.forEach(item => {
            itemMap.set(item.nid, item);
            const circuit = circuitMap.get(item.circuit_nid);
            if (circuit && circuit.itemsByType[item.item_type]) {
                circuit.itemsByType[item.item_type].push(item);
            }
        });

        const isMismatch = (i) => i.status !== 'match' && i.status !== 'warning';
        const mismatchItemCount = data.items.filter(isMismatch).length;
        const statusClass = data.status === 'match' ? 'lvs-pass' : 'lvs-fail';
        const statusText = data.status === 'match' ? 'PASS' : 'FAIL';
        const summaryText = mismatchItemCount > 0
            ? `${mismatchItemCount} mismatch${mismatchItemCount > 1 ? 'es' : ''}`
            : 'All match';

        // Built with createElement/textContent rather than by interpolating
        // into an HTML string: cell, net, device and pin names are design
        // data and may contain characters that would break the markup.
        const header = document.createElement('div');
        header.className = `lvs-header ${statusClass}`;
        const status = document.createElement('span');
        status.className = 'lvs-status';
        status.textContent = statusText;
        const summary = document.createElement('span');
        summary.className = 'lvs-summary';
        summary.textContent = summaryText;
        const deselectBtn = document.createElement('button');
        deselectBtn.className = 'lvs-deselect';
        deselectBtn.disabled = true;
        deselectBtn.textContent = 'Deselect';
        header.append(status, summary, deselectBtn);

        const body = document.createElement('div');
        body.className = 'lvs-body';
        const colHeader = document.createElement('div');
        colHeader.className = 'lvs-col-header';
        colHeader.append(
            textSpan('Objects'), textSpan('Layout'), textSpan('Reference'));
        body.appendChild(colHeader);

        data.circuits.forEach(circuit => {
            const circuitData = circuitMap.get(circuit.nid);
            const allItems = Object.values(circuitData.itemsByType).flat();
            const hasMismatches = circuit.status !== 'match' || allItems.some(isMismatch);

            if (!hasMismatches && allItems.length === 0) return;

            const circuitEl = document.createElement('div');
            circuitEl.className = 'lvs-circuit';
            circuitEl.dataset.nid = circuit.nid;

            const circuitHeader = document.createElement('div');
            circuitHeader.className = 'lvs-circuit-header';
            const circuitLabel = document.createElement('span');
            circuitLabel.append(toggleSpan(), ' ',
                this.statusIcon(circuit.status), ' Circuit');
            // Layout/reference cells link to the circuit pair's layout/
            // schematic view if the corresponding ref resolved.
            circuitHeader.append(
                circuitLabel,
                this.circuitCell(circuit, 'layout', circuit.has_layout_ref,
                    circuit.layout_name, 'Open layout'),
                this.circuitCell(circuit, 'schem', circuit.has_schem_ref,
                    circuit.schem_name, 'Open schematic'));
            circuitEl.appendChild(circuitHeader);

            for (const itemType of TYPE_ORDER) {
                const items = circuitData.itemsByType[itemType];
                if (items.length === 0) continue;

                const mismatchCount = items.filter(isMismatch).length;
                const warningCount = items.filter(i => i.status === 'warning').length;
                const groupStatusIcon = mismatchCount > 0
                    ? this.statusIcon('mismatch')
                    : this.statusIcon(warningCount > 0 ? 'warning' : 'match');

                const groupEl = document.createElement('div');
                groupEl.className = 'lvs-type-group';
                groupEl.dataset.type = itemType;

                const typeHeader = document.createElement('div');
                typeHeader.className = 'lvs-type-header';
                const typeLabel = document.createElement('span');
                typeLabel.append(toggleSpan(), ' ', groupStatusIcon,
                    ` ${TYPE_LABELS[itemType]} (${items.length})`);
                // The two empty cells keep the three-column grid aligned.
                typeHeader.append(typeLabel, textSpan(''), textSpan(''));
                groupEl.appendChild(typeHeader);

                const itemsEl = document.createElement('div');
                itemsEl.className = 'lvs-type-items';
                for (const item of items) {
                    const statusClass = item.status === 'match'
                        ? 'lvs-status-match'
                        : (item.status === 'warning' ? 'lvs-status-warning' : 'lvs-status-mismatch');
                    const layoutName = item.layout_name || '?';
                    const schemName = item.schem_name || '?';
                    const layoutParams = this.formatParams(item.layout_params);
                    const schemParams = this.formatParams(item.schem_params);
                    // The whole row is one click target; underline the
                    // first cell as the suggested click target if
                    // selecting the row highlights anything in the
                    // layout/schematic viewer.
                    const highlightTargets = [];
                    if (item.layout_pos !== null && item.layout_pos !== undefined) highlightTargets.push('layout');
                    if (item.schem_nid !== null && item.schem_nid !== undefined) highlightTargets.push('schematic');
                    const rowLabel = `${layoutName} ${ARROW_BOTH} ${schemName}`;
                    let labelCell;
                    if (highlightTargets.length > 0) {
                        labelCell = textSpan(rowLabel);
                        labelCell.className = 'lvs-item-link';
                        labelCell.title =
                            `Highlight in ${highlightTargets.join(' and ')}`;
                    } else {
                        labelCell = document.createTextNode(rowLabel);
                    }

                    const rowEl = document.createElement('div');
                    rowEl.className = `lvs-item-row ${statusClass}`;
                    rowEl.dataset.nid = item.nid;
                    // A selection survives a re-render: the highlight it
                    // placed in the layout/schematic viewers is still
                    // pending there, so the row it came from stays marked
                    // and Deselect stays available to clear both.
                    if (item.nid === this.selectedItemNid) {
                        rowEl.classList.add('selected');
                        deselectBtn.disabled = false;
                    }
                    const objectCell = document.createElement('span');
                    objectCell.append(`${TYPE_ICONS[itemType]} `, labelCell);
                    rowEl.append(
                        objectCell,
                        textSpan(`${layoutName}${layoutParams}`),
                        textSpan(`${schemName}${schemParams}`));
                    itemsEl.appendChild(rowEl);

                    if (item.message) {
                        const msgEl = document.createElement('div');
                        msgEl.className = 'lvs-item-msg';
                        msgEl.textContent = item.message;
                        itemsEl.appendChild(msgEl);
                    }
                }
                groupEl.appendChild(itemsEl);
                circuitEl.appendChild(groupEl);
            }

            body.appendChild(circuitEl);
        });

        this.el.replaceChildren(header, body);
        // The row loop re-marks the selected row and keeps Deselect enabled when
        // the item survived this re-render. Reconcile the cross-viewer highlight
        // with the fresh data: refresh it for a surviving selection (its
        // geometry may have changed), or clear it if the item is gone (else the
        // pending highlight is orphaned in the layout/schematic viewer, out of
        // reach of the now-disabled Deselect button).
        if (this.selectedItemNid !== null) {
            if (this.el.querySelector('.lvs-item-row.selected')) {
                this.emitSelection(itemMap.get(this.selectedItemNid), circuitMap, data, false);
            } else {
                this.deselect();
            }
        }

        this.attachEventHandlers(itemMap, circuitMap, data);
    }

    statusIcon(status) {
        const cls = status === 'match' ? 'match' : (status === 'warning' ? 'warning' : 'mismatch');
        const icon = document.createElement('span');
        icon.className = `lvs-status-icon ${cls}`;
        return icon;
    }

    // One of the two cell-name columns of a circuit header: a click target
    // opening the pair's layout/schematic view where that ref resolved,
    // plain text otherwise (see the lvs-circuit-link handler).
    circuitCell(circuit, kind, hasRef, name, title) {
        const cell = document.createElement('span');
        if (!hasRef) {
            cell.textContent = name || '?';
            return cell;
        }
        // The link is nested inside the grid cell, so that only the name
        // itself is underlined and clickable.
        const link = textSpan(name || '?');
        link.className = 'lvs-circuit-link';
        link.dataset.nid = circuit.nid;
        link.dataset.kind = kind;
        link.title = title;
        cell.appendChild(link);
        return cell;
    }

    formatParams(params) {
        if (!params || Object.keys(params).length === 0) return '';
        const keyParams = ['W', 'L'];
        const parts = [];
        for (const key of keyParams) {
            if (key in params) {
                let val = params[key];
                if (typeof val === 'number') {
                    if (val < 1e-3) val = (val * 1e6).toFixed(2) + 'u';
                    else if (val < 1) val = (val * 1e3).toFixed(2) + 'm';
                    else val = val.toFixed(2);
                }
                parts.push(`${key}=${val}`);
            }
        }
        return parts.length > 0 ? ` [${parts.join(', ')}]` : '';
    }

    setupColumnResize() {
        const header = this.el.querySelector('.lvs-col-header');
        if (!header) return;

        const cols = header.querySelectorAll(':scope > span');
        const body = this.el.querySelector('.lvs-body');

        cols.forEach((col, idx) => {
            if (idx >= cols.length - 1) return;
            const handle = document.createElement('div');
            handle.className = 'lvs-col-resize';
            handle.dataset.colIdx = idx;
            col.appendChild(handle);
        });

        header.addEventListener('mousedown', (e) => {
            const handle = e.target.closest('.lvs-col-resize');
            if (!handle) return;

            e.preventDefault();
            const idx = parseInt(handle.dataset.colIdx, 10);
            const startX = e.clientX;
            const startWidths = [
                cols[idx].getBoundingClientRect().width,
                cols[idx + 1].getBoundingClientRect().width
            ];

            const onMouseMove = (e) => {
                const dx = e.clientX - startX;
                body.style.setProperty(`--lvs-col${idx + 1}`, `${Math.max(80, startWidths[0] + dx)}px`);
                body.style.setProperty(`--lvs-col${idx + 2}`, `${Math.max(80, startWidths[1] - dx)}px`);
            };

            const onMouseUp = () => {
                document.removeEventListener('mousemove', onMouseMove);
                document.removeEventListener('mouseup', onMouseUp);
                document.body.style.removeProperty('cursor');
                document.body.style.removeProperty('user-select');
            };

            document.body.style.cursor = 'col-resize';
            document.body.style.userSelect = 'none';
            document.addEventListener('mousemove', onMouseMove);
            document.addEventListener('mouseup', onMouseUp);
        });
    }

    attachEventHandlers(itemMap, circuitMap, data) {
        this.setupColumnResize();

        this.el.querySelectorAll('.lvs-circuit-header').forEach(header => {
            header.addEventListener('click', () => {
                const circuit = header.parentElement;
                circuit.classList.toggle('expanded');
                header.querySelector('.lvs-toggle').classList.toggle('expanded');
            });
        });

        // Open the circuit pair's layout/schematic view (without
        // selecting/highlighting anything in it). The view expression
        // addresses the LvsCircuitPair node by nid relative to this
        // report view; the wire hash lets the open request focus a
        // panel showing the same subgraph under a different name.
        this.el.querySelectorAll('.lvs-circuit-link').forEach(linkEl => {
            linkEl.addEventListener('click', (e) => {
                e.stopPropagation();  // don't toggle circuit expansion
                if (this.viewOutdated()) return;
                if (!this.viewName) return;
                const nid = parseInt(linkEl.dataset.nid, 10);
                const kind = linkEl.dataset.kind;
                const circuit = circuitMap.get(nid);
                const ref = kind === 'layout' ? 'ref_layout' : 'ref_schematic';
                const event = kind === 'layout' ? 'layout:request-open' : 'schematic:request-open';
                viewEventBus.emit(event, {
                    view: `${this.viewName}.subgraph.cursor_at(${nid}).${ref}`,
                    wireHash: (circuit && (kind === 'layout'
                        ? circuit.layout_wire_hash : circuit.schem_wire_hash)) || null,
                    sourceContainer: this.panelContainer,
                });
            });
        });

        this.el.querySelectorAll('.lvs-type-header').forEach(header => {
            header.addEventListener('click', (e) => {
                e.stopPropagation();
                const group = header.parentElement;
                group.classList.toggle('expanded');
                header.querySelector('.lvs-toggle').classList.toggle('expanded');
            });
        });

        const deselectBtn = this.el.querySelector('.lvs-deselect');
        deselectBtn.addEventListener('click', () => this.deselect());

        this.el.querySelectorAll('.lvs-item-row').forEach(itemEl => {
            itemEl.addEventListener('click', (e) => {
                e.stopPropagation();
                if (this.viewOutdated()) return;
                this.el.querySelectorAll('.lvs-item-row.selected').forEach(el => {
                    el.classList.remove('selected');
                });
                itemEl.classList.add('selected');
                deselectBtn.disabled = false;

                const nid = parseInt(itemEl.dataset.nid, 10);
                this.selectedItemNid = nid;
                const item = itemMap.get(nid);
                if (item) {
                    this.emitSelection(item, circuitMap, data, true);
                }
            });
        });
    }

    // Pushes the given item's selection to the layout/schematic viewers:
    // replaces any previous highlight with this item's position/net (also
    // stashed as the pending 'lvs:select' so a viewer opened/re-rendered later
    // re-applies it). With open=true (a fresh click) the target views are
    // focused or opened; on a re-render refresh (open=false) they are left
    // as-is.
    emitSelection(item, circuitMap, data, open) {
        // Item positions/nids refer to the item's circuit pair: report-level
        // views for the top pair, per-pair views (addressed by circuit nid)
        // for subcircuit pairs.
        const circuit = circuitMap.get(item.circuit_nid);
        const isTop = !circuit || circuit.is_top;
        const viewBase = this.viewName
            ? (isTop ? this.viewName : `${this.viewName}.subgraph.cursor_at(${item.circuit_nid})`)
            : null;
        const layoutView = viewBase ? `${viewBase}.ref_layout` : null;
        const schemView = viewBase ? `${viewBase}.ref_schematic` : null;
        const layoutWireHash = (isTop ? data.layout_wire_hash : circuit.layout_wire_hash) || null;
        const schemWireHash = (isTop ? data.schem_wire_hash : circuit.schem_wire_hash) || null;

        const payload = {
            pos: item.layout_pos,
            schem_nid: item.schem_nid,
            item_type: item.item_type,
            schem_name: item.schem_name || '',
            layoutView,
            schemView,
            layoutWireHash,
            schemWireHash,
        };
        const hasLayoutPos = item.layout_pos !== null && item.layout_pos !== undefined;
        const hasSchemNid = item.schem_nid !== undefined && item.schem_nid !== null;

        // Clear the previous selection everywhere: its highlight may sit in a
        // viewer the new selection does not target.
        viewEventBus.emit('lvs:clear');
        viewEventBus.setPending('lvs:select', payload);

        if (hasLayoutPos) {
            viewEventBus.emit('lvs:layout-select', payload);
        }
        if (hasSchemNid) {
            viewEventBus.emit('lvs:schem-select', payload);
        }

        // Focuses the target views if open (matched by name or wire hash),
        // opens them otherwise.
        if (open && ((hasLayoutPos && layoutView) || (hasSchemNid && schemView))) {
            viewEventBus.emit('lvs:request-open-views', {
                layoutView: hasLayoutPos ? layoutView : null,
                schemView: hasSchemNid ? schemView : null,
                layoutWireHash: hasLayoutPos ? layoutWireHash : null,
                schemWireHash: hasSchemNid ? schemWireHash : null,
                sourceContainer: this.panelContainer,
            });
        }
    }

    // Clears the current selection: unmarks the selected row, disables the
    // Deselect button and drops the pending highlight (both in this report and
    // in any layout/schematic viewer showing it). Used by the Deselect button
    // and on destroy.
    deselect() {
        this.el.querySelectorAll('.lvs-item-row.selected').forEach(el => {
            el.classList.remove('selected');
        });
        this.selectedItemNid = null;
        const deselectBtn = this.el.querySelector('.lvs-deselect');
        if (deselectBtn) {
            deselectBtn.disabled = true;
        }
        viewEventBus.clearPending('lvs:select');
        viewEventBus.emit('lvs:clear');
    }

    destroy() {
        this.deselect();
    }
}
