// SPDX-FileCopyrightText: 2025 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

import { viewEventBus } from './event-bus.js';

const ARROW_COLLAPSED = '▶';
const ARROW_EXPANDED = '▼';

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
    constructor(resContent, viewName, resultViewer, panelContainer) {
        this.resContent = resContent;
        this.viewName = viewName;
        this.resultViewer = resultViewer;
        this.panelContainer = panelContainer;
        this.el = document.createElement('div');
        this.el.className = 'drc-viewer';
        this.selectedItemNid = null;
        resContent.appendChild(this.el);
    }

    update(data, wireHash) {
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

        // Built with createElement/textContent rather than by interpolating
        // into an HTML string: category, cell and shape names are design
        // data and may contain characters that would break the markup.
        const header = document.createElement('div');
        header.className = 'drc-header';
        const summary = document.createElement('span');
        summary.textContent =
            `${totalCount} violations in ${catCount} categories`;
        const deselectBtn = document.createElement('button');
        deselectBtn.className = 'drc-deselect';
        deselectBtn.disabled = true;
        deselectBtn.textContent = 'Deselect';
        header.append(summary, deselectBtn);

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

        const categoriesEl = document.createElement('div');
        categoriesEl.className = 'drc-categories';

        data.categories.forEach(cat => {
            const catData = catMap.get(cat.nid);
            const catEl = document.createElement('div');
            catEl.className = 'drc-category';
            catEl.dataset.nid = cat.nid;

            const toggle = document.createElement('span');
            toggle.className = 'drc-category-toggle';
            toggle.textContent = ARROW_COLLAPSED;
            const name = document.createElement('span');
            name.className = 'drc-category-name';
            name.textContent = cat.name;
            const count = document.createElement('span');
            count.className = 'drc-category-count';
            count.textContent = `(${catData.count})`;
            // The spaces between the inline spans are the only thing
            // separating them; the style sheet adds no margins.
            catEl.append(toggle, ' ', name, ' ', count);

            if (cat.description) {
                const desc = document.createElement('span');
                desc.className = 'drc-category-desc';
                desc.textContent = ` - ${cat.description}`;
                catEl.appendChild(desc);
            }

            const itemsEl = document.createElement('div');
            itemsEl.className = 'drc-items';
            catData.items.forEach((item, idx) => {
                itemsEl.appendChild(
                    this.buildItem(data, item, idx, cellMap, deselectBtn));
            });
            catEl.appendChild(itemsEl);

            catEl.addEventListener('click', (e) => {
                if (e.target.classList.contains('drc-item')) {
                    return;
                }
                catEl.classList.toggle('expanded');
                toggle.textContent = catEl.classList.contains('expanded')
                    ? ARROW_EXPANDED : ARROW_COLLAPSED;
            });

            categoriesEl.appendChild(catEl);
        });

        this.el.replaceChildren(header, categoriesEl);
        // buildItem re-marks the selected row (see below). If the
        // regenerated report no longer contains that item, the selection is
        // gone with it.
        if (!this.el.querySelector('.drc-item.selected')) {
            this.selectedItemNid = null;
        }
    }

    buildItem(data, item, idx, cellMap, deselectBtn) {
        let label = item.shapes.length > 0 ? item.shapes[0].type : 'item';
        const cell = cellMap.get(item.cell_nid);
        const itemEl = document.createElement('div');
        itemEl.classList.add('drc-item');
        itemEl.dataset.nid = item.nid;
        if (cell && !cell.is_top) {
            label += ` (in ${cell.name})`;
            itemEl.classList.add('drc-item-subcell');
            if (!cell.has_layout_ref) {
                // Cannot be highlighted (see click handler);
                // styled non-clickable, with an explanation.
                itemEl.classList.add('drc-item-nohighlight');
                itemEl.title =
                    `Cell '${cell.name}' has no layout view to highlight in`;
            }
        }
        itemEl.textContent = `#${idx + 1}: ${label}`;

        // A selection survives a re-render: the highlight it placed in the
        // layout viewer is still pending there, so the row it came from
        // stays marked and Deselect stays available to clear both.
        if (item.nid === this.selectedItemNid) {
            itemEl.classList.add('selected');
            deselectBtn.disabled = false;
        }

        itemEl.addEventListener('click', () => {
            // An outdated report must not drive navigation or
            // highlights: its nids, positions and hashes may not
            // match the regenerated views.
            if (!this.resultViewer.viewUpToDate) {
                this.resultViewer.flashRefreshBar();
                return;
            }
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
            this.selectedItemNid = item.nid;

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
                    sourceContainer: this.panelContainer,
                });
            }
        });
        return itemEl;
    }

    destroy() {
        viewEventBus.clearPending('drc:select');
        viewEventBus.emit('drc:clear');
    }
}
