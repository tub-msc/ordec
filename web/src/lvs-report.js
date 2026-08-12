// SPDX-FileCopyrightText: 2025 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

import { viewEventBus } from './event-bus.js';

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
export class LvsReport {
    constructor(resContent) {
        this.resContent = resContent;
        this.el = document.createElement('div');
        this.el.className = 'lvs-viewer';
        this.selectedItemNid = null;
        resContent.appendChild(this.el);
    }

    update(data) {
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

        let html = `<div class="lvs-header ${statusClass}">
            <span class="lvs-status">${statusText}</span>
            <span class="lvs-summary">${summaryText}</span>
            <button class="lvs-deselect" disabled>Deselect</button>
        </div>`;
        html += `<div class="lvs-body">
            <div class="lvs-col-header">
                <span>Objects</span>
                <span>Layout</span>
                <span>Reference</span>
            </div>`;

        const typeOrder = ['pin', 'net', 'device', 'subcircuit'];
        const typeLabels = { pin: 'Pins', net: 'Nets', device: 'Devices', subcircuit: 'Subcircuits' };
        const typeIcons = { pin: '&#8660;', net: '&#8593;', device: '&#9649;', subcircuit: '&#9633;' };

        data.circuits.forEach(circuit => {
            const circuitData = circuitMap.get(circuit.nid);
            const allItems = Object.values(circuitData.itemsByType).flat();
            const hasMismatches = circuit.status !== 'match' || allItems.some(isMismatch);

            if (!hasMismatches && allItems.length === 0) return;

            const circuitStatusIcon = this._statusIcon(circuit.status);
            // Layout/reference cells link to the circuit pair's layout/
            // schematic view if the corresponding ref resolved.
            const layoutCell = circuit.has_layout_ref
                ? `<span class="lvs-circuit-link" data-nid="${circuit.nid}" data-kind="layout" title="Open layout">${circuit.layout_name || '?'}</span>`
                : (circuit.layout_name || '?');
            const schemCell = circuit.has_schem_ref
                ? `<span class="lvs-circuit-link" data-nid="${circuit.nid}" data-kind="schem" title="Open schematic">${circuit.schem_name || '?'}</span>`
                : (circuit.schem_name || '?');
            html += `<div class="lvs-circuit" data-nid="${circuit.nid}">
                <div class="lvs-circuit-header">
                    <span><span class="lvs-toggle">&#9654;</span> ${circuitStatusIcon} Circuit</span>
                    <span>${layoutCell}</span>
                    <span>${schemCell}</span>
                </div>`;

            for (const itemType of typeOrder) {
                const items = circuitData.itemsByType[itemType];
                if (items.length === 0) continue;

                const mismatchCount = items.filter(isMismatch).length;
                const warningCount = items.filter(i => i.status === 'warning').length;
                const groupStatusIcon = mismatchCount > 0
                    ? this._statusIcon('mismatch')
                    : this._statusIcon(warningCount > 0 ? 'warning' : 'match');

                html += `<div class="lvs-type-group" data-type="${itemType}">
                    <div class="lvs-type-header">
                        <span><span class="lvs-toggle">&#9654;</span> ${groupStatusIcon} ${typeLabels[itemType]} (${items.length})</span>
                        <span></span>
                        <span></span>
                    </div>
                    <div class="lvs-type-items">`;

                for (const item of items) {
                    const statusClass = item.status === 'match'
                        ? 'lvs-status-match'
                        : (item.status === 'warning' ? 'lvs-status-warning' : 'lvs-status-mismatch');
                    const layoutName = item.layout_name || '?';
                    const schemName = item.schem_name || '?';
                    const layoutParams = this._formatParams(item.layout_params);
                    const schemParams = this._formatParams(item.schem_params);
                    // The whole row is one click target; underline the
                    // first cell as the suggested click target if
                    // selecting the row highlights anything in the
                    // layout/schematic viewer.
                    const highlightTargets = [];
                    if (item.layout_pos !== null && item.layout_pos !== undefined) highlightTargets.push('layout');
                    if (item.schem_nid !== null && item.schem_nid !== undefined) highlightTargets.push('schematic');
                    const rowLabel = `${layoutName} &#8596; ${schemName}`;
                    const labelCell = highlightTargets.length > 0
                        ? `<span class="lvs-item-link" title="Highlight in ${highlightTargets.join(' and ')}">${rowLabel}</span>`
                        : rowLabel;

                    html += `<div class="lvs-item-row ${statusClass}" data-nid="${item.nid}">
                        <span>${typeIcons[itemType]} ${labelCell}</span>
                        <span>${layoutName}${layoutParams}</span>
                        <span>${schemName}${schemParams}</span>
                    </div>`;
                    if (item.message) {
                        html += `<div class="lvs-item-msg">${item.message}</div>`;
                    }
                }

                html += `</div></div>`;
            }

            html += `</div>`;
        });

        html += '</div>';
        this.el.innerHTML = html;

        this._attachEventHandlers(itemMap, circuitMap, data);
        this.itemMap = itemMap;
    }

    _statusIcon(status) {
        const cls = status === 'match' ? 'match' : (status === 'warning' ? 'warning' : 'mismatch');
        return `<span class="lvs-status-icon ${cls}"></span>`;
    }

    _formatParams(params) {
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

    _setupColumnResize() {
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

    _attachEventHandlers(itemMap, circuitMap, data) {
        this._setupColumnResize();

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
                // See the drc-item guard: outdated reports are inert.
                if (this.resultViewer && !this.resultViewer.viewUpToDate) {
                    this.resultViewer.flashRefreshBar();
                    return;
                }
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
                    sourceContainer: this.glContainer,
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
        deselectBtn.addEventListener('click', () => {
            this.el.querySelectorAll('.lvs-item-row.selected').forEach(el => {
                el.classList.remove('selected');
            });
            this.selectedItemNid = null;
            deselectBtn.disabled = true;
            viewEventBus.clearPending('lvs:select');
            viewEventBus.emit('lvs:clear');
        });

        this.el.querySelectorAll('.lvs-item-row').forEach(itemEl => {
            itemEl.addEventListener('click', (e) => {
                e.stopPropagation();
                // See the drc-item guard: outdated reports are inert.
                if (this.resultViewer && !this.resultViewer.viewUpToDate) {
                    this.resultViewer.flashRefreshBar();
                    return;
                }
                this.el.querySelectorAll('.lvs-item-row.selected').forEach(el => {
                    el.classList.remove('selected');
                });
                itemEl.classList.add('selected');
                deselectBtn.disabled = false;

                const nid = parseInt(itemEl.dataset.nid, 10);
                this.selectedItemNid = nid;
                const item = itemMap.get(nid);

                if (item) {
                    // Item positions/nids refer to the item's circuit
                    // pair: report-level views for the top pair,
                    // per-pair views (addressed by circuit nid) for
                    // subcircuit pairs.
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

                    // Clear the previous selection everywhere: its
                    // highlight may sit in a viewer the new selection
                    // does not target.
                    viewEventBus.emit('lvs:clear');
                    viewEventBus.setPending('lvs:select', payload);

                    if (hasLayoutPos) {
                        viewEventBus.emit('lvs:layout-select', payload);
                    }
                    if (hasSchemNid) {
                        viewEventBus.emit('lvs:schem-select', payload);
                    }

                    // Focuses the target views if open (matched by name
                    // or wire hash), opens them otherwise.
                    if ((hasLayoutPos && layoutView) || (hasSchemNid && schemView)) {
                        viewEventBus.emit('lvs:request-open-views', {
                            layoutView: hasLayoutPos ? layoutView : null,
                            schemView: hasSchemNid ? schemView : null,
                            layoutWireHash: hasLayoutPos ? layoutWireHash : null,
                            schemWireHash: hasSchemNid ? schemWireHash : null,
                            sourceContainer: this.glContainer,
                        });
                    }
                }
            });
        });
    }

    destroy() {
        viewEventBus.clearPending('lvs:select');
        viewEventBus.emit('lvs:clear');
    }
}
