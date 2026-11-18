// SPDX-FileCopyrightText: 2026 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

// Context menu: a list of entries ({label, action}) at the pointer position
// of a contextmenu event, replacing the menu of the browser. At most one is
// open; choosing an entry, a pointer down elsewhere, Escape, a wheel motion
// (which zooms or pans the content under the menu) or losing the window
// focus closes it.
let menu = null;

export function closeContextMenu() {
    menu?.remove();
    menu = null;
}

// Returns the menu element; it is connected to the document while open.
export function openContextMenu(event, entries) {
    event.preventDefault();
    closeContextMenu();
    menu = document.createElement('div');
    menu.className = 'context-menu';
    for (const {label, action} of entries) {
        const item = document.createElement('button');
        item.type = 'button';
        item.textContent = label;
        item.onclick = () => {
            closeContextMenu();
            action();
        };
        menu.append(item);
    }
    document.body.append(menu);
    // Kept inside the window.
    const {width, height} = menu.getBoundingClientRect();
    menu.style.left = `${Math.min(event.clientX, window.innerWidth - width)}px`;
    menu.style.top = `${Math.min(event.clientY, window.innerHeight - height)}px`;
    return menu;
}

document.addEventListener('pointerdown', (event) => {
    if (menu && !menu.contains(event.target)) {
        closeContextMenu();
    }
}, true);
document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
        closeContextMenu();
    }
});
document.addEventListener('wheel', closeContextMenu, {capture: true, passive: true});
window.addEventListener('blur', closeContextMenu);
