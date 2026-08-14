// SPDX-FileCopyrightText: 2026 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

/**
 * Split a view name into hierarchical segments at ".", "(" and "[" boundaries,
 * preserving all characters so that segments.join("") === name.
 *
 * Examples:
 *   "Nand2().schematic"          --> ["Nand2", "()", ".schematic"]
 *   "mylib.VoltageDivider().sch" --> ["mylib", ".VoltageDivider", "()", ".sch"]
 *   "mylib['CellName'].layout"   --> ["mylib", "['CellName']", ".layout"]
 *   "__ord_py_source__"          --> ["__ord_py_source__"]
 *
 * A bracket group is one segment including any nested brackets, so
 * parametrized instance names like "Ipwl(I=((0, 0), ('1u', '1m'))).symbol"
 * keep their whole parameter list in a single "(...)" segment.
 */
function splitViewName(name) {
    const segments = [];
    let i = 0;
    while (i < name.length) {
        let j;
        if (name[i] === '(' || name[i] === '[') {
            // Bracket group: consume up to the matching close bracket
            // (or the end of the name, if unbalanced).
            const open = name[i];
            const close = open === '(' ? ')' : ']';
            let depth = 0;
            for (j = i; j < name.length; j++) {
                if (name[j] === open) {
                    depth++;
                } else if (name[j] === close && --depth === 0) {
                    j++;
                    break;
                }
            }
        } else {
            // Dot-prefixed or plain run up to the next delimiter.
            j = i + 1;
            while (j < name.length && !'.(['.includes(name[j])) {
                j++;
            }
        }
        segments.push(name.slice(i, j));
        i = j;
    }
    return segments.length ? segments : [name];
}

/**
 * Build a trie from an array of { segments, viewName } entries.
 * Each node: { label, children: Map<string, node>, viewName: string|null }
 */
function buildTrie(entries) {
    const root = { label: '', children: new Map(), viewName: null };
    for (const { segments, viewName } of entries) {
        let node = root;
        for (const seg of segments) {
            if (!node.children.has(seg)) {
                node.children.set(seg, { label: seg, children: new Map(), viewName: null });
            }
            node = node.children.get(seg);
        }
        node.viewName = viewName;
    }
    return root;
}

/**
 * Collapse non-leaf nodes that have exactly one child which is also a non-leaf.
 * Labels are concatenated directly (delimiters are already part of segment strings).
 * Exception: don't collapse if the tree has only one top-level path overall.
 */
function collapseTrie(root) {
    for (const [key, child] of root.children) {
        collapseTrie(child);
    }

    // Collapse: if this node has exactly one child and neither node nor child
    // is a "dual" node (both leaf and parent), merge them.  Keep going in case
    // the merged result can collapse further.
    while (root.children.size === 1) {
        const [key, child] = root.children.entries().next().value;
        if (root.viewName !== null) break; // root is itself a leaf, stop
        if (child.viewName !== null && child.children.size > 0) break; // child is leaf+parent
        // Merge child into root
        root.children.delete(key);
        root.label = root.label + child.label;
        root.viewName = child.viewName;
        for (const [ck, cv] of child.children) {
            root.children.set(ck, cv);
        }
    }
}

/**
 * Find the path of segment labels from root to the node matching viewName.
 * Returns an array of child keys, or null if not found.
 */
function findPath(node, viewName) {
    if (node.viewName === viewName && node.children.size === 0) {
        return [];
    }
    for (const [key, child] of node.children) {
        if (child.viewName === viewName && child.children.size === 0) {
            return [key];
        }
        const sub = findPath(child, viewName);
        if (sub !== null) {
            return [key, ...sub];
        }
    }
    // Also check if a node is both leaf and parent (direct case)
    if (node.viewName === viewName) {
        return [];
    }
    return null;
}

/**
 * Resize a <select> to fit its currently selected option text.
 * Uses a temporary hidden element to measure the text width.
 */
const _measurer = document.createElement('span');
_measurer.style.cssText =
    'position:absolute;visibility:hidden;white-space:nowrap;pointer-events:none';

function autoWidthSelect(select) {
    const style = getComputedStyle(select);
    _measurer.style.font = style.font;
    _measurer.style.fontSize = style.fontSize;
    _measurer.style.fontFamily = style.fontFamily;
    _measurer.textContent = select.options[select.selectedIndex]?.text || '';
    document.body.appendChild(_measurer);
    // Add padding (left+right from the select) plus room for the dropdown arrow
    const pad = parseFloat(style.paddingLeft) + parseFloat(style.paddingRight) + 20;
    select.style.width = (_measurer.offsetWidth + pad) + 'px';
    _measurer.remove();
}

export class HierSelector {
    constructor(container, { onSelect, onDeselect }) {
        this.container = container;
        this.onSelect = onSelect;
        this.onDeselect = onDeselect || (() => {});
        this.root = null;
        this.selects = [];
        this._selectedView = null;
    }

    get selectedView() {
        return this._selectedView;
    }

    update(viewNames, selectedView) {
        const entries = viewNames.map(name => ({
            segments: splitViewName(name),
            viewName: name,
        }));

        this.root = buildTrie(entries);

        // Only collapse if there's more than one top-level entry
        if (this.root.children.size > 1) {
            for (const [, child] of this.root.children) {
                collapseTrie(child);
            }
        }

        this._render(selectedView);
    }

    _render(selectedView) {
        // Remove old selects
        for (const sel of this.selects) {
            sel.remove();
        }
        this.selects = [];
        this._selectedView = null;

        if (!this.root || this.root.children.size === 0) {
            const select = document.createElement('select');
            select.classList.add('viewsel');
            const opt = document.createElement('option');
            opt.disabled = true;
            opt.selected = true;
            opt.textContent = '---- No views found ----';
            select.appendChild(opt);
            this.container.appendChild(select);
            this.selects.push(select);
            return;
        }

        // Find path to restore selection
        let path = null;
        if (selectedView) {
            path = findPath(this.root, selectedView);
        }

        this._selectedView = this._renderLevel(this.root, 0, path);
    }

    _renderLevel(node, depth, path) {
        const select = document.createElement('select');
        select.classList.add('viewsel');
        this.container.appendChild(select);
        this.selects.push(select);

        // Placeholder
        const placeholder = document.createElement('option');
        placeholder.disabled = true;
        placeholder.value = '';
        placeholder.textContent = depth === 0
            ? '--- Select ---'
            : '---';
        select.appendChild(placeholder);

        // If this node is both a leaf and has children, add a "(direct)" option
        if (node.viewName !== null && node.children.size > 0) {
            const directOpt = document.createElement('option');
            directOpt.value = '__direct__';
            directOpt.textContent = '(direct)';
            select.appendChild(directOpt);
        }

        let selectedKey = null;
        if (path && path.length > 0 && node.children.has(path[0])) {
            selectedKey = path[0];
        } else if (path && path.length === 0 && node.viewName !== null && node.children.size > 0) {
            // The "(direct)" option should be selected
            selectedKey = '__direct__';
        }

        const sortedChildren = [...node.children.entries()].sort((a, b) =>
            a[0].localeCompare(b[0])
        );

        for (const [key, child] of sortedChildren) {
            const opt = document.createElement('option');
            opt.value = key;
            opt.textContent = child.label;
            select.appendChild(opt);

            if (key === selectedKey) {
                opt.selected = true;
            }
        }

        // Resolved leaf view name for this subtree (null if nothing is
        // selected down this branch); returned to the caller rather than
        // stashed on the instance.
        let resolvedView = null;
        if (selectedKey === '__direct__') {
            select.querySelector('option[value="__direct__"]').selected = true;
            resolvedView = node.viewName;
        } else if (!selectedKey) {
            placeholder.selected = true;
        }

        select.onchange = () => this._onSelectChange(node, select, depth);
        autoWidthSelect(select);

        // If we have a path to follow, render the next level
        if (selectedKey && selectedKey !== '__direct__' && node.children.has(selectedKey)) {
            const child = node.children.get(selectedKey);
            if (child.children.size > 0) {
                resolvedView = this._renderLevel(child, depth + 1, path ? path.slice(1) : null);
            } else {
                // It's a leaf — set as selected
                resolvedView = child.viewName;
            }
        }
        return resolvedView;
    }

    _onSelectChange(node, select, depth) {
        autoWidthSelect(select);
        // Capture selected values from deeper selects before removing them
        const previousPath = [];
        for (let i = depth + 1; i < this.selects.length; i++) {
            const val = this.selects[i].value;
            if (!val) break; // stop at unselected placeholder
            previousPath.push(val);
        }

        // Remove selects deeper than this one
        while (this.selects.length > depth + 1) {
            this.selects.pop().remove();
        }

        const key = select.value;
        if (!key) return;

        // Handle "(direct)" option
        if (key === '__direct__') {
            this._selectedView = node.viewName;
            this.onSelect(node.viewName);
            return;
        }

        const child = node.children.get(key);
        if (!child) return;

        if (child.children.size > 0) {
            // Non-leaf: try to carry forward previous deeper selections
            const resolvedView = this._renderLevel(child, depth + 1, previousPath.length > 0 ? previousPath : null);
            this._selectedView = resolvedView;
            if (resolvedView) {
                this.onSelect(resolvedView);
            } else {
                this.onDeselect();
                this._guideToNextSelect();
            }
        } else {
            // Leaf: fire selection
            this._selectedView = child.viewName;
            this.onSelect(child.viewName);
        }
    }

    // Pop open the deepest still-unselected dropdown to guide the user
    // onward. showPicker() requires transient user activation, which
    // Chromium grants inside the change event of the previous dropdown
    // but Firefox does not (the option click happens in the native popup
    // widget, not on the page); there the dropdown is only focused, so
    // Enter/Alt+Down opens it. The attempt is deferred a frame so it
    // cannot race with the closing popup of the previous dropdown.
    _guideToNextSelect() {
        this._openSelect(this.selects[this.selects.length - 1]);
    }

    // Pop open the first dropdown, e.g. right after the result viewer was
    // created via the toolbar button, whose click provides the user
    // activation that showPicker() needs (in every browser, here).
    openFirst() {
        this._openSelect(this.selects[0]);
    }

    _openSelect(select) {
        if (!select || select.value) {
            return;
        }
        select.focus();
        if (select.showPicker) {
            requestAnimationFrame(() => {
                try {
                    select.showPicker();
                } catch (e) {
                    // no transient user activation: focus alone must do
                }
            });
        }
    }
}
