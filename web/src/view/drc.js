// SPDX-FileCopyrightText: 2025 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

import { View } from './view.js';

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
export class DrcView extends View {
    constructor(resContent, viewName, resultViewer, panelContainer) {
        super(resContent, viewName, resultViewer, panelContainer);
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

        deselectBtn.addEventListener('click', () => this.deselect());

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
        // buildItem re-marks the selected row and keeps Deselect enabled when
        // the item survived this re-render. Reconcile the cross-viewer highlight
        // with the fresh data: refresh it for a surviving selection (its
        // geometry may have changed), or clear it if the item is gone (else the
        // pending highlight is orphaned in the layout viewer, out of reach of
        // the now-disabled Deselect button).
        if (this.selectedItemNid !== null) {
            if (this.el.querySelector('.drc-item.selected')) {
                this.emitSelection(itemMap.get(this.selectedItemNid), data, cellMap, false);
            } else {
                this.deselect();
            }
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
            if (this.viewOutdated()) return;
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
            this.emitSelection(item, data, cellMap, true);
        });
        return itemEl;
    }

    // Pushes the given item's selection to the layout viewer: replaces any
    // previous highlight with this item's shapes (also stashed as the pending
    // 'drc:select' so a viewer opened/re-rendered later re-applies it). With
    // open=true (a fresh click) the target layout view is focused or opened;
    // on a re-render refresh (open=false) it is left as-is.
    emitSelection(item, data, cellMap, open) {
        const cell = cellMap.get(item.cell_nid);
        const isTop = !cell || cell.is_top;
        const layoutView = this.viewName
            ? (isTop
                ? `${this.viewName}.ref_layout`
                : `${this.viewName}.subgraph.cursor_at(${item.cell_nid}).ref_layout`)
            : null;
        const layoutWireHash = (isTop ? data.layout_wire_hash : cell.layout_wire_hash) || null;
        // Clear the previous selection everywhere: its highlight may sit in a
        // viewer the new selection does not target.
        this.eventBus.emit('drc:clear');
        const payload = { shapes: item.shapes, layoutView, layoutWireHash };
        this.eventBus.setPending('drc:select', payload);
        this.eventBus.emit('drc:select', payload);
        if (open && layoutView) {
            // Focuses the target view if open (matched by name or wire hash),
            // opens it otherwise.
            this.eventBus.emit('layout:request-open', {
                view: layoutView,
                wireHash: layoutWireHash,
                sourceContainer: this.panelContainer,
            });
        }
    }

    // Clears the current selection: unmarks the selected row, disables the
    // Deselect button and drops the pending highlight (both in this report and
    // in any layout viewer showing it). Used by the Deselect button and on
    // destroy.
    deselect() {
        this.el.querySelectorAll('.drc-item.selected').forEach(el => {
            el.classList.remove('selected');
        });
        this.selectedItemNid = null;
        const deselectBtn = this.el.querySelector('.drc-deselect');
        if (deselectBtn) {
            deselectBtn.disabled = true;
        }
        this.eventBus.clearPending('drc:select');
        this.eventBus.emit('drc:clear');
    }

    destroy() {
        this.deselect();
    }
}
