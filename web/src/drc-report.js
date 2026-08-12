// SPDX-FileCopyrightText: 2025 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

import { viewEventBus } from './event-bus.js';

// DRC Report viewer.
//
// Event bus protocol:
//   drc:select {shapes, layoutView, layoutWireHash} - sent when an item is
//     selected
//   drc:clear - sent on deselect or destroy
//
// Pending mechanism: setPending('drc:select', payload) stores the
// selection for layout viewers opened later; it stays pending until
// deselect or destroy, like lvs:select. Payloads are targeted, so a
// later-opened viewer applies it only if it shows the target view
// (reopening that view restores the highlight).
//
// View naming: items of the top cell target "<viewName>.ref_layout",
// items of subcells target
// "<viewName>.subgraph.cursor_at(<cell_nid>).ref_layout", addressing
// the DrcCell node by nid. Every payload carries its layoutView plus
// the cell's subgraph wire hash (layoutWireHash), so only viewers showing
// that view highlight - matched by name, or by hash for a viewer
// showing the same subgraph under a different view name: shape
// coordinates are only meaningful in the item's own cell, and an
// untargeted broadcast would paint them into unrelated layout views.
// Subcell items whose DrcCell has no resolved ref_layout (e.g. KLayout
// variant cells) cannot be highlighted anywhere and are not selectable.
export class DrcReport {
    constructor(resContent) {
        this.resContent = resContent;
        this.el = document.createElement('div');
        this.el.className = 'drc-viewer';
        this.selectedItemNid = null;
        resContent.appendChild(this.el);
    }

    update(data) {
        const catMap = new Map();
        data.categories.forEach(cat => {
            catMap.set(cat.nid, { ...cat, items: [], count: 0 });
        });

        const cellMap = new Map();
        (data.cells || []).forEach(cell => {
            cellMap.set(cell.nid, cell);
        });

        const itemMap = new Map();
        data.items.forEach(item => {
            itemMap.set(item.nid, item);
            const cat = catMap.get(item.category_nid);
            if (cat) {
                cat.items.push(item);
                cat.count++;
            }
        });

        const totalCount = data.items.length;
        const catCount = data.categories.length;

        let html = `<div class="drc-header">
            <span>${totalCount} violations in ${catCount} categories</span>
            <button class="drc-deselect" disabled>Deselect</button>
        </div>`;
        html += '<div class="drc-categories">';

        data.categories.forEach(cat => {
            const catData = catMap.get(cat.nid);
            html += `<div class="drc-category" data-nid="${cat.nid}">`;
            html += `<span class="drc-category-toggle">&#9654;</span> `;
            html += `<span class="drc-category-name">${cat.name}</span>`;
            html += ` <span class="drc-category-count">(${catData.count})</span>`;
            if (cat.description) {
                html += `<span class="drc-category-desc"> - ${cat.description}</span>`;
            }
            html += '<div class="drc-items">';
            catData.items.forEach((item, idx) => {
                let label = item.shapes.length > 0
                    ? item.shapes[0].type
                    : 'item';
                const cell = cellMap.get(item.cell_nid);
                let cls = 'drc-item';
                let title = '';
                if (cell && !cell.is_top) {
                    label += ` (in ${cell.name})`;
                    cls += ' drc-item-subcell';
                    if (!cell.has_layout_ref) {
                        // Cannot be highlighted (see click handler);
                        // styled non-clickable, with an explanation.
                        cls += ' drc-item-nohighlight';
                        title = ` title="Cell '${cell.name}' has no layout view to highlight in"`;
                    }
                }
                html += `<div class="${cls}" data-nid="${item.nid}"${title}>#${idx + 1}: ${label}</div>`;
            });
            html += '</div></div>';
        });

        html += '</div>';
        this.el.innerHTML = html;

        this.el.querySelectorAll('.drc-category').forEach(catEl => {
            const toggleCategory = () => {
                catEl.classList.toggle('expanded');
                const toggle = catEl.querySelector('.drc-category-toggle');
                toggle.innerHTML = catEl.classList.contains('expanded') ? '&#9660;' : '&#9654;';
            };
            catEl.addEventListener('click', (e) => {
                if (!e.target.classList.contains('drc-item')) {
                    toggleCategory();
                }
            });
        });

        const deselectBtn = this.el.querySelector('.drc-deselect');
        const deselect = () => {
            this.el.querySelectorAll('.drc-item.selected').forEach(el => {
                el.classList.remove('selected');
            });
            this.selectedItemNid = null;
            deselectBtn.disabled = true;
            viewEventBus.clearPending('drc:select');
            viewEventBus.emit('drc:clear');
        };
        deselectBtn.addEventListener('click', deselect);

        this.el.querySelectorAll('.drc-item').forEach(itemEl => {
            itemEl.addEventListener('click', () => {
                // An outdated report must not drive navigation or
                // highlights: its nids, positions and hashes may not
                // match the regenerated views.
                if (this.resultViewer && !this.resultViewer.viewUpToDate) {
                    this.resultViewer.flashRefreshBar();
                    return;
                }
                const nid = parseInt(itemEl.dataset.nid, 10);
                const item = itemMap.get(nid);
                if (!item) return;
                const cell = cellMap.get(item.cell_nid);
                const isTop = !cell || cell.is_top;
                // Subcell shapes are in the cell's local coordinate
                // space; without a resolved ref_layout there is no view
                // where they could be highlighted correctly.
                if (!isTop && !cell.has_layout_ref) return;

                this.el.querySelectorAll('.drc-item.selected').forEach(el => {
                    el.classList.remove('selected');
                });
                itemEl.classList.add('selected');
                deselectBtn.disabled = false;
                this.selectedItemNid = nid;

                const layoutView = this.viewName
                    ? (isTop
                        ? `${this.viewName}.ref_layout`
                        : `${this.viewName}.subgraph.cursor_at(${item.cell_nid}).ref_layout`)
                    : null;
                const layoutWireHash = (isTop ? data.layout_wire_hash : cell.layout_wire_hash) || null;
                // Clear the previous selection everywhere: its highlight
                // may sit in a viewer the new selection does not target.
                viewEventBus.emit('drc:clear');
                const payload = { shapes: item.shapes, layoutView, layoutWireHash };
                viewEventBus.setPending('drc:select', payload);
                viewEventBus.emit('drc:select', payload);
                if (layoutView) {
                    // Focuses the target view if open (matched by name
                    // or wire hash), opens it otherwise.
                    viewEventBus.emit('layout:request-open', {
                        view: layoutView,
                        wireHash: layoutWireHash,
                        sourceContainer: this.glContainer,
                    });
                }
            });
        });

        this.itemMap = itemMap;
    }

    destroy() {
        viewEventBus.clearPending('drc:select');
        viewEventBus.emit('drc:clear');
    }
}
