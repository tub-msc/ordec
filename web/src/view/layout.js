// SPDX-FileCopyrightText: 2025 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

import * as d3 from "d3";
import { mat4, vec2 } from "gl-matrix";
import earcut from 'earcut';

import { siFormat } from './siformat.js';
import { View, CoordinateDisplay } from './view.js';
import {
    BLEND_MODES, PATTERN_SIZE, patternAtlas,
    applyStyle, applyStyleChange, savePrefs, resetPrefs, isPref, styleSettings,
    isLightBackground, intensity, layerFill, layerLook, layerOrder, drawSwatch,
    showLayerEditor, buildStylePanel,
} from './layout-style.js';

// See: https://github.com/mdn/dom-examples/blob/main/webgl-examples/tutorial/sample2/webgl-demo.js

import glslShapesVert from './glsl/layout-shapes.vert';
import glslShapesFrag from './glsl/layout-shapes.frag';
import glslGridVert from './glsl/layout-grid.vert';
import glslPostVert from './glsl/layout-post.vert';
import glslPostFrag from './glsl/layout-post.frag';
import glslLabelsVert from './glsl/layout-labels.vert';
import glslLabelsFrag from './glsl/layout-labels.frag';
import glslHighlightVert from './glsl/layout-highlight.vert';
import glslHighlightFrag from './glsl/layout-highlight.frag';

// Width in CSS pixels of DRC/LVS highlight outlines (box/edge/poly shapes):
const HIGHLIGHT_LINE_WIDTH = 2.0;
// Width in CSS pixels of the LVS crosshair marker lines:
const CROSSHAIR_LINE_WIDTH = 2.0;

function loadShader(gl, type, source) {
    const shader = gl.createShader(type);

    gl.shaderSource(shader, source);
    gl.compileShader(shader);

    if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
        alert(`Error compiling shaders: ${gl.getShaderInfoLog(shader)}`);
        gl.deleteShader(shader);
        return null;
    }

    return shader;
}

/**
 * Tracks WebGL resources created through it so they can all be released
 * in a single destroy() call. WebGL resources live in GPU memory and are
 * not reclaimed by the JS garbage collector. Forgetting to delete them
 * leaks GPU memory and could eventually exhaust the browser's per-document
 * WebGL limits.
 */
class GLResourceRegistry {
    constructor(gl) {
        this.gl = gl;
        this.textures = [];
        this.buffers = [];
        this.framebuffers = [];
        this.programs = [];
    }

    createTexture() {
        const t = this.gl.createTexture();
        this.textures.push(t);
        return t;
    }

    createBuffer() {
        const b = this.gl.createBuffer();
        this.buffers.push(b);
        return b;
    }

    createFramebuffer() {
        const f = this.gl.createFramebuffer();
        this.framebuffers.push(f);
        return f;
    }

    createProgram(vsSource, fsSource) {
        const gl = this.gl;
        const vertexShader = loadShader(gl, gl.VERTEX_SHADER, vsSource);
        const fragmentShader = loadShader(gl, gl.FRAGMENT_SHADER, fsSource);

        const prog = gl.createProgram();
        gl.attachShader(prog, vertexShader);
        gl.attachShader(prog, fragmentShader);
        gl.linkProgram(prog);

        if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) {
            alert(`Unable to initialize shader program: ${gl.getProgramInfoLog(prog)}`);
            return null;
        }

        // Flag shaders for deletion. They remain alive (because they are
        // attached to the program) until the program itself is deleted, at
        // which point they are freed automatically. Without these calls the
        // shader objects would leak when the program is later deleted.
        gl.deleteShader(vertexShader);
        gl.deleteShader(fragmentShader);

        this.programs.push(prog);
        return prog;
    }

    destroy() {
        const gl = this.gl;
        for (const t of this.textures) gl.deleteTexture(t);
        for (const b of this.buffers) gl.deleteBuffer(b);
        for (const f of this.framebuffers) gl.deleteFramebuffer(f);
        for (const p of this.programs) gl.deleteProgram(p);
        this.textures = [];
        this.buffers = [];
        this.framebuffers = [];
        this.programs = [];
    }
}

// Unique ids for the layer list's checkbox/label pairs.
let idCounter = 0;
function generateId() {
    idCounter += 1;
    return "idgen" + idCounter;
}

// Layout transforms are [a, b, c, d, tx, ty]: x' = a*x + b*y + tx,
// y' = c*x + d*y + ty (see docs/dev/webui.rst).
function composeTransforms(m1, m2) {
    // m1 applied after m2:
    return [
        m1[0]*m2[0] + m1[1]*m2[2], m1[0]*m2[1] + m1[1]*m2[3],
        m1[2]*m2[0] + m1[3]*m2[2], m1[2]*m2[1] + m1[3]*m2[3],
        m1[0]*m2[4] + m1[1]*m2[5] + m1[4], m1[2]*m2[4] + m1[3]*m2[5] + m1[5],
    ];
}

function transformPoint(m, p) {
    return [m[0]*p[0] + m[1]*p[1] + m[4], m[2]*p[0] + m[3]*p[1] + m[5]];
}

export class LayoutView extends View {
    constructor(resContent, viewName, resultViewer, panelContainer) {
        super(resContent, viewName, resultViewer, panelContainer);
        this.transform = d3.zoomIdentity.scale(1e-1,1e-1);
        this.projectionMatrix = mat4.create();
        this.visibility = new Map();
        // Style settings: LayoutStyle and viewer preferences (see
        // layout-style.js).
        this.style = {};
        applyStyle(this.style, null);
        this.hoverNid = null; // layer under the mouse in the layer list
        this.initialZoomDone = false;

        this.root = document.createElement('div');
        this.root.classList.add('layout-viewer');
        this.canvas = document.createElement('canvas');
        this.canvas.classList.add('layoutFit');
        this.sidebar = document.createElement('div');
        this.sidebar.classList.add('layout-sidebar');
        this.sidebarToggle = document.createElement('button');
        this.sidebarToggle.classList.add('layout-sidebar-toggle');
        this.sidebarToggle.type = 'button';
        this.sidebarToggle.textContent = 'Layers';
        this.sidebarToggle.setAttribute('aria-expanded', 'true');
        this.sidebarToggle.title = 'Hide layers';
        this.sidebarToggle.onclick = () => this.toggleSidebar();
        this.layersUl = document.createElement('ul');
        this.layersUl.classList.add('layerList');
        this.stylePanel = buildStylePanel(this.style,
            (keys, commit) => this.onStyleChange(keys, commit), () => this.resetStyle());
        this.sidebar.append(
            this.sidebarToggle,
            this.stylePanel.element,
            this.layersUl
        );
        this.root.append(this.canvas, this.sidebar);
        this.resContent.replaceChildren(this.root);

        this.canvas.width = this.canvas.clientWidth;
        this.canvas.height = this.canvas.clientHeight;

        this.gl = this.canvas.getContext("webgl2");
        if (this.gl === null) {
            alert("WebGL initialization failed!");
            return;
        }

        this.initGL();

        this.zoom = d3.zoom().on( 'zoom',  ({transform}) => {
            this.transform = transform;
            this.drawGL();
        });

        d3.select(this.canvas).call(this.zoom).call(this.zoom.transform, this.transform);

        this.resizeObserver = new ResizeObserver((entries) => {
            // Guard against callbacks that arrive after destroy().
            if (!this.gl) return;
            if((this.canvas.clientWidth == 0) || (this.canvas.clientHeight == 0)) {
                return;
            }
            this.canvas.width = this.canvas.clientWidth;
            this.canvas.height = this.canvas.clientHeight;
            this.drawGL();
        });
        this.resizeObserver.observe(this.canvas);

        this.onKeydown = this.onKeydown.bind(this);
        this.onMousemove = this.onMousemove.bind(this);
        this.onMouseleave = () => this.clearMousePosition();
        this.resContent.addEventListener("keydown", this.onKeydown);
        this.canvas.addEventListener("mousemove", this.onMousemove);
        this.canvas.addEventListener("mouseleave", this.onMouseleave);

        this.onDrcSelect = (data) => {
            // DRC selections target the view of the violation's cell; they
            // apply to viewers showing that view: matched by name, or by
            // wire hash for a viewer showing the same subgraph under a
            // different view name.
            if (data && !this.selectionApplies(data.layoutView, data.layoutWireHash)) {
                return;
            }
            this.setHighlight(data.shapes);
        };
        this.onDrcClear = () => this.clearHighlight();
        this.busSubscribe('drc:select', this.onDrcSelect);
        this.busSubscribe('drc:clear', this.onDrcClear);

        this.onLvsSelect = (data) => {
            // Selections targeted at a specific layout view (items of LVS
            // subcircuit pairs) apply to viewers showing that view, matched
            // by name or by wire hash.
            if (data && !this.selectionApplies(data.layoutView, data.layoutWireHash)) {
                return;
            }
            this.highlightPos(data.pos);
        };
        this.onLvsClear = () => this.clearHighlight();
        this.busSubscribe('lvs:layout-select', this.onLvsSelect);
        this.busSubscribe('lvs:clear', this.onLvsClear);

        // Style changes of any layout viewer (this one included, see
        // saveStyle) apply to all viewers showing the same LayoutStyle.
        this.onLayoutStyleChange = ({key, settings, layers}) => {
            if (!this.data || this.style.key !== key) return;
            applyStyleChange(this.style, this.data.layers, settings, layers);
            this.stylePanel.sync();
            this.updateLayerList();
            this.updateLayers();
        };
        this.busSubscribe('layoutstyle:change', this.onLayoutStyleChange);

        // Selections made before this view was opened; taken by update(),
        // once there is layout data to highlight in and a wire hash to match.
        this.pendingDrc = this.eventBus.getPending('drc:select');
        this.pendingLvs = this.eventBus.getPending('lvs:select');

        this.onPagehide = () => this.destroy();
        window.addEventListener('pagehide', this.onPagehide);
    }


    zoomToBox(lx, ly, ux, uy, animate, padFraction = 0.05) {
        if(lx == ux && ly == uy) {
            // A single point has no size to fit and would produce an
            // infinite scale below; expand it to an arbitrary finite box.
            lx -= 1000;
            ux += 1000;
            ly -= 1000;
            uy += 1000;
        }
        const pad = Math.max(ux-lx, uy-ly) * padFraction;
        lx -= pad;
        ux += pad;
        ly -= pad;
        uy += pad;

        const w = ux - lx;
        const h = uy - ly;

        // The layers sidebar overlays the right edge of the canvas, so fit
        // into the unobstructed part only. offsetWidth reflects the current
        // sidebar state: expanded width or the narrow collapsed strip.
        // canvas.width is set from clientWidth, so both are in CSS pixels.
        const availWidth = Math.max(this.canvas.width - this.sidebar.offsetWidth, 1);
        const availHeight = this.canvas.height;

        const scaleX = availWidth / w;
        const scaleY = availHeight / h;
        const scale = Math.min(scaleX, scaleY);
        let newZoom = new d3.ZoomTransform(scale, -lx*scale, uy*scale);

        // Center within the available area; the term for the scale-limiting
        // axis is zero, so both axes can be adjusted unconditionally.
        newZoom.x += (availWidth - w*newZoom.k)/2;
        newZoom.y += (availHeight - h*newZoom.k)/2;

        if(animate) {
            d3.select(this.canvas).transition().duration(400).call(this.zoom.transform, newZoom);
        } else {
            d3.select(this.canvas).call(this.zoom.transform, newZoom);
        }
    }

    zoomFull(animate) {
        if(!this.data.extent) {
            return; // empty layout, nothing to fit
        }
        const [lx, ly, ux, uy] = this.data.extent;
        this.zoomToBox(lx, ly, ux, uy, animate);
    }

    onKeydown(event) {
        if(event.key == "f") {
            this.zoomFull(true);
        }
    }

    toggleSidebar() {
        this.sidebar.classList.toggle('layout-sidebar-collapsed');
        const expanded = !this.sidebar.classList.contains(
            'layout-sidebar-collapsed'
        );
        this.sidebarToggle.setAttribute('aria-expanded', String(expanded));
        this.sidebarToggle.title = expanded ? 'Hide layers' : 'Show layers';
    }

    clearMousePosition() {
        this.cursorCoordinates?.clear();
    }

    onMousemove(event) {
        if (!this.data || !this.cursorCoordinates) return;
        const pos = this.transform.invert([event.offsetX, event.offsetY]);
        const x = siFormat(pos[0], this.data.unit);
        const y = siFormat(-pos[1], this.data.unit);
        this.cursorCoordinates.set(x, y);
    }

    pendingApplies(pending) {
        return this.selectionApplies(pending.layoutView, pending.layoutWireHash);
    }

    update(msgData, wireHash) {
        this.data = msgData;
        this.wireHash = wireHash;
        applyStyle(this.style, msgData.style);
        this.stylePanel.sync();
        this.loadPatterns();
        this.prepareHierarchy();

        // Populate the sidebar before any zoom-to-fit below, so that its
        // final width is known when the fit area (the part of the canvas
        // not covered by the sidebar) is computed.
        this.loadShapes();
        this.loadLabels(false);
        this.updateLayerList();

        // Pending selections are applied exactly once, without zooming; when
        // this is the first update, the selection also supplies the zoom
        // target, so that opening a layout from a DRC/LVS report lands on the
        // selected item just like a live drc:select/lvs:layout-select does.
        let zoomToSelection = null;
        const pendingDrc = this.takePendingSelection('pendingDrc');
        if (pendingDrc) {
            const box = this.setHighlight(pendingDrc.shapes, false);
            if (box) {
                zoomToSelection = () => this.zoomToBox(...box, true, 0.25);
            }
        }
        const pendingLvs = this.takePendingSelection('pendingLvs');
        if (pendingLvs) {
            // Applied after the DRC highlight, which it replaces, so its zoom
            // target wins as well.
            this.highlightPos(pendingLvs.pos, false);
            zoomToSelection = () => this.zoomToPos(pendingLvs.pos);
        }

        if(!this.initialZoomDone) {
            if (zoomToSelection) {
                zoomToSelection();
                this.initialZoomDone = true;
            } else if (this.data.extent) {
                // An empty layout has no extent to fit; leave initialZoomDone
                // unset so the first update that delivers actual content
                // triggers the fit (there is no viewport worth preserving on
                // an empty layout).
                this.zoomFull(false);
                this.initialZoomDone = true;
            }
        }

        this.updateLayers();
    }

    updateLayerList() {
        const layersUl = this.layersUl;
        layersUl.innerHTML = "";

        let li;
        let id;

        li = document.createElement('li');
        id = generateId()
        li.innerHTML = `
            <input type="checkbox" checked class="allLayers" id="${id}" name="all">
            <label for="${id}"><b>all</b></label> 
        `;
        layersUl.appendChild(li);
        // The swatch under the mouse (if any) is removed with the list.
        this.hoverNid = null;
        // The list is in drawing order (bottom first).
        this.drawOrder = layerOrder(this.data.layers);
        this.drawOrder.forEach(layer => {
            li = document.createElement('li');
            li.classList.add('layerItem');
            id = generateId();
            li.innerHTML = `
                <input type="checkbox" class="singleLayer" id="${id}" name="${layer.nid}">
                <canvas class="layerSwatch"></canvas>
                <label for="${id}">${layer.path}</label>
            `;
            const swatch = li.querySelector('canvas');
            drawSwatch(swatch, layerLook(layer, this.style), this.style);
            if (this.style.key !== null) {
                swatch.title = 'Click to edit';
                swatch.onclick = () => showLayerEditor(this.root, swatch, layer, this.style,
                    entry => this.saveStyle({}, {[layer.path]: entry}));
            }
            // Only the swatch emphasizes its layer (and shows it if hidden,
            // see isShown): hovering the checkbox or name (e.g. while toggling
            // visibility) leaves the view as is.
            swatch.onmouseenter = () => this.setHoverLayer(layer.nid);
            swatch.onmouseleave = () => this.setHoverLayer(null);
            layersUl.appendChild(li);
        });
        this.layerCheckboxes = layersUl.querySelectorAll('.singleLayer');
        this.layerCheckboxes.forEach(checkbox => {
            const layerNid = Number(checkbox.name);
            // Set checked to true both for true and undefined value returned by get():
            checkbox.checked = (this.visibility.get(layerNid)!=false);
            checkbox.onclick = () => this.updateLayers();
        });

        this.allLayerCheckbox = layersUl.querySelector('.allLayers');

        this.allLayerCheckbox.onclick = () => {
            this.layerCheckboxes.forEach(checkbox => {
                checkbox.checked = this.allLayerCheckbox.checked;
            });
            this.updateLayers();
        };

        this.cursorCoordinates = new CoordinateDisplay({
            tagName: 'li',
            classNames: ['layout-coordinates'],
        });
        layersUl.appendChild(this.cursorCoordinates.element);
    }

    // Uploads the fill patterns of the style, stacked vertically (see
    // patternAtlas); a layer's pattern is drawn by its index in them.
    loadPatterns() {
        const gl = this.gl;
        const patterns = this.style.patterns;
        this.patternIndex = new Map(patterns.map((p, i) => [p.name, i]));
        gl.bindTexture(gl.TEXTURE_2D, this.patternTexture);
        gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
        gl.texImage2D(gl.TEXTURE_2D, 0, gl.R8, PATTERN_SIZE, PATTERN_SIZE * Math.max(1, patterns.length),
            0, gl.RED, gl.UNSIGNED_BYTE, patternAtlas(patterns));
    }

    // Called by the style panel after the settings keys of this.style
    // changed (see buildStylePanel).
    onStyleChange(keys, commit) {
        if (keys.some(isPref)) {
            savePrefs(this.style);
        }
        const settings = keys.filter(k => !isPref(k));
        if (commit && settings.length && this.style.key !== null) {
            // Redraws via onLayoutStyleChange.
            this.saveStyle(styleSettings(this.style, settings), {});
            return;
        }
        if (!this.data) return;
        if (keys.every(k => k == 'brightness' || k == 'opacity')) {
            // Not shown in the layer list: redraw only.
            this.drawGL();
        } else {
            // Swatches, patterns or order changed: rebuild the list.
            this.updateLayerList();
            this.updateLayers();
        }
    }

    // Changes the user's customization of the LayoutStyle (see
    // update_customization in src/ordec/layout/style.py): applied locally by
    // all viewers of the style right away, and saved by the server. If saving
    // fails, the change stays on display with an error.
    saveStyle(settings, layers) {
        this.eventBus.emit('layoutstyle:change', {key: this.style.key, settings, layers});
        this.resultViewer.client.setLayoutStyle(this.style.key, settings, layers, exception => {
            this.stylePanel.setError(exception && `Not saved: ${exception.message}`);
        });
    }

    // Resets the viewer preferences and removes the settings and layers of
    // the customization file (see onLayoutStyleChange for the redraw).
    resetStyle() {
        resetPrefs(this.style);
        if (this.style.customized) {
            this.saveStyle(
                Object.fromEntries(this.style.userSettings.map(k => [k, null])),
                Object.fromEntries(this.style.userLayers.map(path => [path, null])));
        } else {
            this.stylePanel.sync();
            this.drawGL();
        }
    }

    // Whether a layer is drawn: if visible (checked or never unchecked), or
    // while its swatch is hovered, which shows hidden layers too.
    isShown(nid) {
        return this.visibility.get(nid) != false || nid == this.hoverNid;
    }

    setHoverLayer(nid) {
        this.hoverNid = nid;
        this.drawGL();
    }

    destroy() {
        // Called by ResultViewer when this renderer is being replaced,
        // or on page unload via pagehide event.
        this.busUnsubscribeAll();
        this.resContent.removeEventListener("keydown", this.onKeydown);
        this.canvas.removeEventListener("mousemove", this.onMousemove);
        this.canvas.removeEventListener("mouseleave", this.onMouseleave);
        window.removeEventListener('pagehide', this.onPagehide);
        if (!this.gl) return;
        this.resizeObserver.disconnect();
        this.glResources.destroy();
        const loseContext = this.gl.getExtension('WEBGL_lose_context');
        if (loseContext) loseContext.loseContext();
        this.gl = null;
    }

    initGL() {
        const gl = this.gl;

        gl.getExtension("EXT_color_buffer_float");
        gl.getExtension("EXT_float_blend");

        this.glResources = new GLResourceRegistry(gl);
        this.programInfos = {};
        let prog;

        prog = this.glResources.createProgram(glslShapesVert, glslShapesFrag);
        this.programInfos.shapes = {
            program: prog,
            attribLocations: {
                vertexPosition: gl.getAttribLocation(prog, "aVertexPosition"),
                transformX: gl.getAttribLocation(prog, "aTransformX"),
                transformY: gl.getAttribLocation(prog, "aTransformY"),
            },
            uniformLocations: {
                projectionMatrix: gl.getUniformLocation(prog, "uProjectionMatrix"),
                depth: gl.getUniformLocation(prog, "uDepth"),
                mode: gl.getUniformLocation(prog, "uMode"),
                color: gl.getUniformLocation(prog, "uColor"),
                gain: gl.getUniformLocation(prog, "uGain"),
                weight: gl.getUniformLocation(prog, "uWeight"),
                pattern: gl.getUniformLocation(prog, "uPattern"),
                patternCount: gl.getUniformLocation(prog, "uPatternCount"),
                patternMul: gl.getUniformLocation(prog, "uPatternMul"),
                patternAdd: gl.getUniformLocation(prog, "uPatternAdd"),
                patterns: gl.getUniformLocation(prog, "uPatterns"),
            },
        };

        // The grid shares the fragment shader of the highlight program.
        prog = this.glResources.createProgram(glslGridVert, glslHighlightFrag);
        this.programInfos.grid = {
            program: prog,
            attribLocations: {
                vertexPosition: gl.getAttribLocation(prog, "aVertexPosition"),
            },
            uniformLocations: {
                projectionMatrix: gl.getUniformLocation(prog, "uProjectionMatrix"),
                modelViewMatrix: gl.getUniformLocation(prog, "uModelViewMatrix"),
                viewport: gl.getUniformLocation(prog, "uViewport"),
                color: gl.getUniformLocation(prog, "uColor"),
            },
        };

        prog = this.glResources.createProgram(glslLabelsVert, glslLabelsFrag);
        this.programInfos.labels = {
            program: prog,
            attribLocations: {
                vertexPosition: gl.getAttribLocation(prog, "aVertexPosition"),
                vertexTextureCoord: gl.getAttribLocation(prog, "aTextureCoord"),
                vertexPixelCoord: gl.getAttribLocation(prog, "aPixelCoord"),
            },
            uniformLocations: {
                projectionMatrix: gl.getUniformLocation(prog, "uProjectionMatrix"),
                modelViewMatrix: gl.getUniformLocation(prog, "uModelViewMatrix"),
                pixelScale: gl.getUniformLocation(prog, "uPixelScale"),
                sampler: gl.getUniformLocation(prog, "uSampler"),
                invert: gl.getUniformLocation(prog, "uInvert"),
            },
        };

        prog = this.glResources.createProgram(glslHighlightVert, glslHighlightFrag);
        this.programInfos.highlight = {
            program: prog,
            attribLocations: {
                position: gl.getAttribLocation(prog, "aPosition"),
                segStart: gl.getAttribLocation(prog, "aSegStart"),
                segEnd: gl.getAttribLocation(prog, "aSegEnd"),
                side: gl.getAttribLocation(prog, "aSide"),
            },
            uniformLocations: {
                projectionMatrix: gl.getUniformLocation(prog, "uProjectionMatrix"),
                modelViewMatrix: gl.getUniformLocation(prog, "uModelViewMatrix"),
                viewport: gl.getUniformLocation(prog, "uViewport"),
                halfWidth: gl.getUniformLocation(prog, "uHalfWidth"),
                color: gl.getUniformLocation(prog, "uColor"),
            },
        };

        prog = this.glResources.createProgram(glslPostVert, glslPostFrag);
        this.programInfos.post = {
            program: prog,
            attribLocations: {
                vertexPosition: gl.getAttribLocation(prog, "aVertexPosition"),
                vertexTextureCoord: gl.getAttribLocation(prog, "aTextureCoord"),
            },
            uniformLocations: {
                projectionMatrix: gl.getUniformLocation(prog, "uProjectionMatrix"),
                sampler: gl.getUniformLocation(prog, "uSampler"),
                mode: gl.getUniformLocation(prog, "uMode"),
                bg: gl.getUniformLocation(prog, "uBg"),
                gain: gl.getUniformLocation(prog, "uGain"),
            },
        };

        // Fill patterns of the style (see loadPatterns):
        this.patternTexture = this.glResources.createTexture();
        gl.bindTexture(gl.TEXTURE_2D, this.patternTexture);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
        this.loadPatterns();

        this.intermediateTexture = this.glResources.createTexture();
        this.intermediateTextureDepth = this.glResources.createTexture();
        this.intermediateFramebuffer = this.glResources.createFramebuffer();
        this.labelsTexture = this.glResources.createTexture();

        this.buffers = {
            // static, loaded by loadBuffersConstant:
            gridVertices: this.glResources.createBuffer(),
            postVertices: this.glResources.createBuffer(),

            // dynamic, loaded by loadBuffersDynamic:
            shapeVertices: this.glResources.createBuffer(),
            placementTransforms: this.glResources.createBuffer(),
            labelVertices: this.glResources.createBuffer(),

            // highlight overlay for DRC:
            highlightVertices: this.glResources.createBuffer(),
        }
        this.highlightNumVertices = 0;

        this.loadBuffersConstant();

        this.width = -1;
        this.height = -1;
    }

    loadLabels(isFontSwap) {
        const gl = this.gl; 
        let labelVertices = [];
        this.labelsNumVertices = 0;

        const fontSpec = '20px Inconsolata';

        if(!document.fonts.check(fontSpec) && !isFontSwap) {
            // Font is not yet loaded, font swap needed:
            document.fonts.load(fontSpec).then(() => {
                // Guard against the font resolving after destroy().
                if (!this.gl) return;
                console.log("reloading labels");
                this.loadLabels(true);
                this.drawGL();
            });
        }

        const ctx = document.createElement("canvas").getContext("2d");
        // Resizing the canvas resets the context state, so this is applied
        // again once the atlas size is known.
        const setupCtx = () => {
            ctx.font = fontSpec;
            ctx.fontStretch = "semi-condensed";
            ctx.textAlign = "left";
            ctx.textBaseline = "top";
        };
        setupCtx();
        // All lines share one height, so that multi-line labels stack evenly
        // and the atlas rows are uniform.
        const lineHeight = Math.ceil(ctx.measureText("").fontBoundingBoxDescent);

        // Collect labels and measure each distinct line (canvas fillText does
        // not break lines at "\n", so every line gets its own atlas slot).
        const lineWidths = new Map();
        const labels = this.data.layers.map(layer => {
            const layerLabels = [];
            this.drawItems.forEach(item => {
                const entry = this.cellLayers[item.cell].get(layer.nid);
                entry?.labels.forEach(label => {
                    const [x, y] = transformPoint(item.m, label.pos);
                    const lines = label.text.split("\n");
                    lines.forEach(line => {
                        if(!lineWidths.has(line)) {
                            lineWidths.set(line, Math.ceil(ctx.measureText(line).width));
                        }
                    });
                    layerLabels.push({x, y, lines});
                });
            });
            return layerLabels;
        });

        // Size the atlas to fit the widest line. A line wider than
        // MAX_TEXTURE_SIZE is cut at the atlas width, with its quad narrowed
        // accordingly: texture coordinates must never leave the line's slot.
        const maxSize = gl.getParameter(gl.MAX_TEXTURE_SIZE);
        let widest = 512;
        lineWidths.forEach(W => { widest = Math.max(widest, W); });
        this.labelsTextureWidth = Math.min(maxSize, widest);
        let cursorX = 0;
        let cursorY = 0;
        // Set on the first line that no longer fits the atlas, so that the
        // remaining lines are skipped without alerting once per line.
        let textureFull = false;
        this.labelsTextureMap = new Map();
        lineWidths.forEach((W, line) => {
            W = Math.min(W, this.labelsTextureWidth);
            if(W == 0) {
                return;
            }
            if(cursorX + W > this.labelsTextureWidth) {
                cursorX = 0;
                cursorY += lineHeight;
            }
            if(cursorY + lineHeight > maxSize) {
                if(!textureFull) {
                    textureFull = true;
                    alert(`Labels texture is full! Some labels are not displayed.`);
                }
                return;
            }
            this.labelsTextureMap.set(line, {x: cursorX, y: cursorY, width: W});
            cursorX += W;
        });
        this.labelsTextureHeight = cursorY + lineHeight;

        ctx.canvas.width  = this.labelsTextureWidth;
        ctx.canvas.height = this.labelsTextureHeight;
        setupCtx();
        ctx.fillStyle = "#000000";
        ctx.fillRect(0, 0, this.labelsTextureWidth, this.labelsTextureHeight);
        ctx.fillStyle = "#ffffff";
        this.labelsTextureMap.forEach((tex, line) => {
            ctx.fillText(line, tex.x, tex.y);
        });

        // Adds one line of a label. The label is centered on (x, y), and
        // each of its lines is centered horizontally.
        const addLine = (x, y, line, p_yl) => {
            const tex = this.labelsTextureMap.get(line);
            // Empty line or atlas full: nothing to draw.
            if(tex === undefined) {
                return;
            }

            const lu = (tex.x) / this.labelsTextureWidth;
            const uu = (tex.x + tex.width) / this.labelsTextureWidth;
            const lv = (tex.y) / this.labelsTextureHeight;
            const uv = (tex.y + lineHeight) / this.labelsTextureHeight;

            const p_xl = -Math.ceil(tex.width/2);
            const p_xu = p_xl + tex.width;
            const p_yu = p_yl + lineHeight;

            labelVertices.push(
                // x y    textureCoord   pixelCoord
                x, y,     uu, lv,        p_xu, p_yl,
                x, y,     uu, uv,        p_xu, p_yu,
                x, y,     lu, uv,        p_xl, p_yu,
                x, y,     uu, lv,        p_xu, p_yl,
                x, y,     lu, uv,        p_xl, p_yu,
                x, y,     lu, lv,        p_xl, p_yl,
            );
            this.labelsNumVertices += 6;
        };

        this.data.layers.forEach((layer, i) => {
            layer.labelVerticesOffset = this.labelsNumVertices;
            labels[i].forEach(({x, y, lines}) => {
                const top = -Math.ceil(lines.length * lineHeight / 2);
                lines.forEach((line, j) => addLine(x, y, line, top + j * lineHeight));
            });
            layer.labelVerticesCount = this.labelsNumVertices - layer.labelVerticesOffset;
        });

        gl.bindTexture(gl.TEXTURE_2D, this.labelsTexture);
        gl.texImage2D(gl.TEXTURE_2D, 0, gl.R8, gl.RED, gl.UNSIGNED_BYTE, ctx.canvas);

        gl.bindBuffer(gl.ARRAY_BUFFER, this.buffers.labelVertices);
        gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(labelVertices), gl.STATIC_DRAW);
    }

    prepareHierarchy() {
        // The layout arrives as cells (distinct layouts, cell 0 is the top)
        // with per-layer geometry and instances of other cells (see
        // docs/dev/webui.rst). Each cell's geometry is loaded once. There
        // is one draw item per placement of a cell in the top cell; all
        // placements of a cell are drawn by one instanced draw call, with
        // the items' transforms as per-instance attributes.
        const gl = this.gl;
        const cells = this.data.cells;
        this.layerByNid = new Map(this.data.layers.map(l => [l.nid, l]));
        this.cellLayers = cells.map(cell => new Map(cell.layers.map(e => [e.layer, e])));
        this.drawItems = [];
        const walk = (cellIdx, m) => {
            this.drawItems.push({cell: cellIdx, m: m});
            const inst = cells[cellIdx].instances;
            for (let i = 0; i < inst.cell.length; i++) {
                walk(inst.cell[i], composeTransforms(m, inst.transform.subarray(6*i, 6*i + 6)));
            }
        };
        walk(0, [1, 0, 0, 1, 0, 0]);

        // Sort by cell, so that the placements of one cell form one
        // contiguous run of the placementTransforms buffer.
        this.drawItems.sort((a, b) => a.cell - b.cell);
        this.cellPlacements = cells.map(() => ({first: 0, count: 0}));
        const buf = new Float32Array(6 * this.drawItems.length);
        this.drawItems.forEach((item, i) => {
            const m = item.m;
            // Row order, as expected by aTransformX and aTransformY:
            buf.set([m[0], m[1], m[4], m[2], m[3], m[5]], 6*i);
            const placements = this.cellPlacements[item.cell];
            if (placements.count == 0) {
                placements.first = i;
            }
            placements.count++;
        });
        gl.bindBuffer(gl.ARRAY_BUFFER, this.buffers.placementTransforms);
        gl.bufferData(gl.ARRAY_BUFFER, buf, gl.STATIC_DRAW);
    }

    loadShapes() {
        const gl = this.gl;

        // For all shapes, separate triangle (fill), line (outline) and cross
        // line vertex "segments" are loaded into the shapeVertices buffer,
        // per cell and layer, irrespective of whether the layer's style uses
        // them. This way, style changes (see onLayoutStyleChange) need no
        // reload.

        // First pass: triangulate polygons and count vertices.
        let numVertices = 0;
        this.data.cells.forEach(cell => cell.layers.forEach(entry => {
            const nRects = entry.rects.length / 4;
            const offs = entry.polyOffsets;
            entry.polyTriangles = [];
            let lines = nRects * 8;
            let cross = nRects * 4;
            let tris = nRects * 6;
            for (let p = 0; p < offs.length - 1; p++) {
                const nv = offs[p+1] - offs[p];
                const triangles = earcut(entry.polyCoords.subarray(2*offs[p], 2*offs[p+1]));
                entry.polyTriangles.push(triangles);
                lines += 2*nv;
                cross += nv == 4 ? 4 : 0;
                tris += triangles.length;
            }
            entry.lineCount = lines;
            entry.crossCount = cross;
            entry.triCount = tris;
            numVertices += lines + cross + tris;
        }));

        // Second pass: fill the buffer.
        const buf = new Float32Array(2 * numVertices);
        let n = 0; // vertices written
        const push = (x, y) => { buf[2*n] = x; buf[2*n + 1] = y; n++; };
        this.data.cells.forEach(cell => cell.layers.forEach(entry => {
            const r = entry.rects;
            const offs = entry.polyOffsets;
            const c = entry.polyCoords;

            entry.lineOffset = n;
            for (let i = 0; i < r.length; i += 4) {
                const lx = r[i], ly = r[i+1], ux = r[i+2], uy = r[i+3];
                push(lx, ly); push(ux, ly);
                push(ux, ly); push(ux, uy);
                push(ux, uy); push(lx, uy);
                push(lx, uy); push(lx, ly);
            }
            for (let p = 0; p < offs.length - 1; p++) {
                const s = 2*offs[p];
                const e = 2*offs[p+1];
                push(c[s], c[s+1]);
                for (let i = s + 2; i < e; i += 2) {
                    // twice: first to end last line, second to start next line
                    push(c[i], c[i+1]);
                    push(c[i], c[i+1]);
                }
                push(c[s], c[s+1]);
            }

            // "X" through rectangles and four-vertex polygons, drawn for
            // layers with styleCrossRect.
            entry.crossOffset = n;
            for (let i = 0; i < r.length; i += 4) {
                const lx = r[i], ly = r[i+1], ux = r[i+2], uy = r[i+3];
                push(lx, ly); push(ux, uy);
                push(ux, ly); push(lx, uy);
            }
            for (let p = 0; p < offs.length - 1; p++) {
                const s = 2*offs[p];
                if (offs[p+1] - offs[p] == 4) {
                    push(c[s], c[s+1]); push(c[s+4], c[s+5]);
                    push(c[s+2], c[s+3]); push(c[s+6], c[s+7]);
                }
            }

            entry.triOffset = n;
            for (let i = 0; i < r.length; i += 4) {
                const lx = r[i], ly = r[i+1], ux = r[i+2], uy = r[i+3];
                push(lx, ly); push(ux, ly); push(ux, uy);
                push(lx, ly); push(ux, uy); push(lx, uy);
            }
            for (let p = 0; p < offs.length - 1; p++) {
                const s = 2*offs[p];
                entry.polyTriangles[p].forEach(idx => push(c[s + 2*idx], c[s + 2*idx + 1]));
            }
            delete entry.polyTriangles;
        }));

        gl.bindBuffer(gl.ARRAY_BUFFER, this.buffers.shapeVertices);
        gl.bufferData(gl.ARRAY_BUFFER, buf, gl.STATIC_DRAW);
    }

    loadBuffersConstant() {
        // For postprocessing: Load a screen-filling rectangle (two triangles)
        // with texture coordinates:

        const gl = this.gl;

        gl.bindBuffer(gl.ARRAY_BUFFER, this.buffers.postVertices);
        gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([
            // x y      u  v
             1,  1,     1, 1,
             1, -1,     1, 0,
            -1, -1,     0, 0,
             1,  1,     1, 1,
            -1, -1,     0, 0,
            -1,  1,     0, 1,
        ]), gl.STATIC_DRAW);
    
            
        // Load grid buffer:

        gl.bindBuffer(gl.ARRAY_BUFFER, this.buffers.gridVertices);
        this.gridSize = 128;
        const grid = [];
        for(let x = 0; x < this.gridSize; x++) {
            for(let y = 0; y < this.gridSize; y++) {
                grid.push(x, y);
            }
        }
        gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(grid), gl.STATIC_DRAW);
    }

    drawGLShapes() {
        const gl = this.gl;
        const style = this.style;
        const programInfo = this.programInfos.shapes;
        const {vertexPosition, transformX, transformY} = programInfo.attribLocations;
        const u = programInfo.uniformLocations;
        const mode = BLEND_MODES.findIndex(([key]) => key == style.blend);

        gl.useProgram(programInfo.program);

        gl.bindFramebuffer(gl.FRAMEBUFFER, this.intermediateFramebuffer);

        gl.enable(gl.BLEND);
        if (style.blend == 'over') {
            // Premultiplied alpha, back to front:
            gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
            gl.blendEquation(gl.FUNC_ADD);
        } else if (style.blend == 'max') {
            gl.blendFunc(gl.ONE, gl.ONE);
            gl.blendEquation(gl.MAX);
        } else {
            gl.blendFunc(gl.ONE, gl.ONE);
            gl.blendEquation(gl.FUNC_ADD);
        }

        // Every layer gets its own depth value; with depth func NOTEQUAL,
        // overlapping shapes of one layer affect each pixel only once.
        gl.enable(gl.DEPTH_TEST);
        gl.depthFunc(gl.NOTEQUAL);

        gl.clearColor(0.0, 0.0, 0.0, 0.0);
        gl.clearDepth(1.0);

        gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);

        gl.uniformMatrix4fv(u.projectionMatrix, false, this.projectionMatrix);
        gl.uniform1i(u.mode, mode);
        const k = intensity(style);
        // At the default intensity, additive matches the original viewer.
        const gain = {additive: k * Math.exp(-20/15), over: 1, mix: 1, max: k, ink: 0.25 * k};
        gl.uniform1f(u.gain, gain[style.blend]);

        // Pattern pixel coordinates (see layout-shapes.frag):
        const ps = style.patternScale;
        gl.uniform1f(u.patternCount, Math.max(1, this.style.patterns.length));
        // Screen pixels, y pointing down; with 'pan', shifted along with the
        // layout when panning, so that patterns do not swim.
        const pan = style.patternAnchor == 'pan';
        const tx = pan ? Math.round(this.transform.x) : 0;
        const ty = pan ? Math.round(this.transform.y) : 0;
        gl.uniform2fv(u.patternMul, [1/ps, -1/ps]);
        gl.uniform2fv(u.patternAdd, [-tx/ps, (this.height - ty)/ps]);
        gl.activeTexture(gl.TEXTURE0);
        gl.bindTexture(gl.TEXTURE_2D, this.patternTexture);
        gl.uniform1i(u.patterns, 0);

        gl.bindBuffer(gl.ARRAY_BUFFER, this.buffers.shapeVertices);
        gl.vertexAttribPointer(vertexPosition, 2, gl.FLOAT, false, 0, 0);
        gl.enableVertexAttribArray(vertexPosition);

        // The transform attributes advance per instance (placement), not per
        // vertex. Their pointers are set per cell in drawLayer.
        gl.bindBuffer(gl.ARRAY_BUFFER, this.buffers.placementTransforms);
        gl.enableVertexAttribArray(transformX);
        gl.enableVertexAttribArray(transformY);
        gl.vertexAttribDivisor(transformX, 1);
        gl.vertexAttribDivisor(transformY, 1);

        const drawLayer = (layer, color, mode, offsetKey, countKey) => {
            gl.uniform3fv(u.color, color.map(v => v / 255));
            this.cellLayers.forEach((layers, cellIdx) => {
                const entry = layers.get(layer.nid);
                const placements = this.cellPlacements[cellIdx];
                if (entry && entry[countKey] > 0 && placements.count > 0) {
                    // WebGL2 has no base instance parameter, so the cell's
                    // run of transforms is selected by the byte offset.
                    const offset = placements.first * 6*4;
                    gl.vertexAttribPointer(transformX, 3, gl.FLOAT, false, 6*4, offset);
                    gl.vertexAttribPointer(transformY, 3, gl.FLOAT, false, 6*4, offset + 3*4);
                    gl.drawArraysInstanced(mode, entry[offsetKey], entry[countKey], placements.count);
                }
            });
        };

        // The hovered layer is emphasized by dimming the others, and drawn
        // on top in over mode.
        const hover = this.hoverNid;
        let order = this.drawOrder.filter(layer => this.isShown(layer.nid));
        if (hover !== null && style.blend == 'over') {
            order = order.filter(l => l.nid != hover).concat(order.filter(l => l.nid == hover));
        }
        const emphasis = layer => (hover === null || layer.nid == hover) ? 1.0 : 0.2;
        const fillWeight = style.blend == 'over' ? style.opacity : 1.0;

        const drawOutline = (layer, depth) => {
            const color = layer.styleStroke;
            if (color) {
                gl.uniform1f(u.depth, depth);
                gl.uniform1f(u.weight, emphasis(layer));
                gl.uniform1f(u.pattern, -1);
                drawLayer(layer, color, gl.LINES, 'lineOffset', 'lineCount');
                if (layer.styleCrossRect) {
                    drawLayer(layer, color, gl.LINES, 'crossOffset', 'crossCount');
                }
            }
        };
        order.forEach((layer, i) => {
            const depth = (i + 1) / 4096;
            drawOutline(layer, depth);
            const fill = layerFill(layer, style);
            if (fill) {
                gl.uniform1f(u.depth, depth);
                gl.uniform1f(u.weight, fillWeight * emphasis(layer));
                gl.uniform1f(u.pattern, layer.pattern === null ? -1 : this.patternIndex.get(layer.pattern));
                drawLayer(layer, fill, gl.TRIANGLES, 'triOffset', 'triCount');
            }
        });

        // Vertex attribute state is shared by all programs (no vertex array
        // objects are used), so the divisors must not leak into later draws.
        gl.vertexAttribDivisor(transformX, 0);
        gl.vertexAttribDivisor(transformY, 0);
    }

    drawGLGrid() {
        // Drawn onto the canvas after drawGLPost, in a contrasting color.
        const gl = this.gl;
        const programInfo = this.programInfos.grid;

        gl.useProgram(programInfo.program);
        gl.bindFramebuffer(gl.FRAMEBUFFER, null);
        gl.disable(gl.BLEND);
        gl.disable(gl.DEPTH_TEST);

        gl.bindBuffer(gl.ARRAY_BUFFER, this.buffers.gridVertices);
        gl.vertexAttribPointer(programInfo.attribLocations.vertexPosition, 2, gl.FLOAT, false, 0, 0);
        gl.enableVertexAttribArray(programInfo.attribLocations.vertexPosition);

        const v = isLightBackground(this.style) ? 0.0 : 1.0;
        gl.uniform4fv(programInfo.uniformLocations.color, [v, v, v, 1.0]);
        gl.uniform2fv(programInfo.uniformLocations.viewport, [this.width, this.height]);
        gl.uniformMatrix4fv(programInfo.uniformLocations.projectionMatrix, false, this.projectionMatrix);
        gl.uniformMatrix4fv(programInfo.uniformLocations.modelViewMatrix, false, this.scaleGrid());

        gl.drawArrays(gl.POINTS, 0, this.gridSize * this.gridSize);
    }

    drawGLLabels() {
        const gl = this.gl;
        const programInfo = this.programInfos.labels;

        gl.useProgram(programInfo.program);

        gl.bindFramebuffer(gl.FRAMEBUFFER, null);

        // Light text with MAX blending, or dark text with MIN blending on
        // light backgrounds.
        const light = isLightBackground(this.style);
        gl.enable(gl.BLEND);
        gl.blendFunc(gl.ONE, gl.ONE);
        gl.blendEquation(light ? gl.MIN : gl.MAX);
        gl.uniform1f(programInfo.uniformLocations.invert, light ? 1.0 : 0.0);

        gl.disable(gl.DEPTH_TEST);

        gl.activeTexture(gl.TEXTURE0);
        gl.bindTexture(gl.TEXTURE_2D, this.labelsTexture);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
        gl.uniform1i(programInfo.uniformLocations.sampler, 0);
        
        gl.bindBuffer(gl.ARRAY_BUFFER, this.buffers.labelVertices);
        gl.vertexAttribPointer(programInfo.attribLocations.vertexPosition, 2, gl.FLOAT, false, 6*4, 0);
        gl.vertexAttribPointer(programInfo.attribLocations.vertexTextureCoord, 2, gl.FLOAT, false, 6*4, 2*4);
        gl.vertexAttribPointer(programInfo.attribLocations.vertexPixelCoord, 2, gl.FLOAT, false, 6*4, 4*4);
        gl.enableVertexAttribArray(programInfo.attribLocations.vertexPosition);
        gl.enableVertexAttribArray(programInfo.attribLocations.vertexTextureCoord);
        gl.enableVertexAttribArray(programInfo.attribLocations.vertexPixelCoord);

        gl.uniform2fv(programInfo.uniformLocations.pixelScale, [2/this.width,2/this.height])
        gl.uniformMatrix4fv(programInfo.uniformLocations.projectionMatrix, false, this.projectionMatrix);
        gl.uniformMatrix4fv(programInfo.uniformLocations.modelViewMatrix, false, mat4.create());

        this.data.layers.forEach(layer => {
            if (!this.isShown(layer.nid)) {
                return;
            }

            if(layer.labelVerticesCount > 0) {
                gl.drawArrays(gl.TRIANGLES, layer.labelVerticesOffset, layer.labelVerticesCount);
            }
        });
    }

    scaleGrid() {
        const projectionMatrixInv = mat4.create();
        mat4.invert(projectionMatrixInv, this.projectionMatrix);

        // If the canvas is small, make the grid smaller to prevent it from being too dense:
        const canvasMaxExtent = Math.max(this.width, this.height);
        const gridMaxDensity = 20; // maximum density: one dot / 20 pixels
        const adjustedGridSize = Math.min(canvasMaxExtent/gridMaxDensity, this.gridSize);

        const topRight = vec2.create();
        const bottomLeft = vec2.create();
        vec2.transformMat4(topRight, vec2.fromValues(1, 1), projectionMatrixInv);
        vec2.transformMat4(bottomLeft, vec2.fromValues(-1, -1), projectionMatrixInv);
        const width = topRight[0] - bottomLeft[0];
        const height = topRight[1] - bottomLeft[1];
        const maxExtent = Math.max(width, height);
        const scale = 10**Math.ceil(Math.log10(maxExtent/(adjustedGridSize-2)));

        const modelViewMatrix = mat4.create();
        mat4.scale(modelViewMatrix, modelViewMatrix, [scale, scale, 1]);
        const gridTranslX = Math.floor(bottomLeft[0] / scale);
        const gridTranslY = Math.floor(bottomLeft[1] / scale);
        mat4.translate(modelViewMatrix, modelViewMatrix, [gridTranslX, gridTranslY, 0]);
        return modelViewMatrix;
    }

    drawGLPost() {
        const gl = this.gl;
        const programInfo = this.programInfos.post;

        gl.useProgram(programInfo.program);
        gl.disable(gl.BLEND);
        gl.disable(gl.DEPTH_TEST);

        gl.bindFramebuffer(gl.FRAMEBUFFER, null);
        
        gl.activeTexture(gl.TEXTURE0);
        gl.bindTexture(gl.TEXTURE_2D, this.intermediateTexture);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
        gl.uniform1i(programInfo.uniformLocations.sampler, 0);
        gl.uniform1i(programInfo.uniformLocations.mode,
            BLEND_MODES.findIndex(([key]) => key == this.style.blend));
        gl.uniform3fv(programInfo.uniformLocations.bg, this.style.background);
        gl.uniform1f(programInfo.uniformLocations.gain, 1.5 * intensity(this.style));

        gl.bindBuffer(gl.ARRAY_BUFFER, this.buffers.postVertices);
        gl.vertexAttribPointer(programInfo.attribLocations.vertexPosition, 2, gl.FLOAT, false, 4*4, 0);
        gl.vertexAttribPointer(programInfo.attribLocations.vertexTextureCoord, 2, gl.FLOAT, false, 4*4, 2*4);
        gl.enableVertexAttribArray(programInfo.attribLocations.vertexPosition);
        gl.enableVertexAttribArray(programInfo.attribLocations.vertexTextureCoord);

        const projectionMatrix = mat4.create();
        mat4.orthoNO(projectionMatrix, -1, 1, -1, 1, -1, 1);
        gl.uniformMatrix4fv(programInfo.uniformLocations.projectionMatrix, false, projectionMatrix);

        gl.drawArrays(gl.TRIANGLES, 0, 6);
    }

    resizeGL() {
        const gl = this.gl;

        // Configure canvas framebuffer width + height:

        gl.bindFramebuffer(gl.FRAMEBUFFER, null);
        gl.viewport(0, 0, this.width, this.height);

        // (Re)size intermediate framebuffer textures:

        gl.bindFramebuffer(gl.FRAMEBUFFER, this.intermediateFramebuffer);

        gl.bindTexture(gl.TEXTURE_2D, this.intermediateTexture);
        gl.texImage2D(
            gl.TEXTURE_2D,
            0,
            gl.RGBA32F,
            this.width,
            this.height,
            0,
            gl.RGBA,
            gl.FLOAT,
            null
        );
        gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, this.intermediateTexture, 0);

        gl.bindTexture(gl.TEXTURE_2D, this.intermediateTextureDepth);
        gl.texImage2D(
            gl.TEXTURE_2D,
            0,
            gl.DEPTH_COMPONENT32F,
            this.width,
            this.height,
            0,
            gl.DEPTH_COMPONENT,
            gl.FLOAT,
            null
        );
        gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.DEPTH_ATTACHMENT, gl.TEXTURE_2D, this.intermediateTextureDepth, 0);
    }

    updateProjectionMatrix() {
        mat4.orthoNO(this.projectionMatrix, 0, this.width, this.height, 0, -1, 1);
        mat4.translate(this.projectionMatrix, this.projectionMatrix, [this.transform.x, this.transform.y, 0]);
        mat4.scale(this.projectionMatrix, this.projectionMatrix, [this.transform.k, this.transform.k, 1]);

        // Rectify axis orientation: X points right, Y points _up_.
        mat4.scale(this.projectionMatrix, this.projectionMatrix, [1, -1, 1]);
    }

    highlightPos(pos, zoomTo = true) {
        if (!pos) {
            this.crosshairPos = null;
            this.clearHighlight();
            return;
        }
        this.crosshairPos = pos;
        this.updateCrosshair();
        if (zoomTo) {
            this.zoomToPos(pos);
        }
    }

    // A crosshair position has no extent of its own to fit, so it is framed
    // by a fixed-size box around it.
    zoomToPos(pos) {
        const r = 2000;
        const [x, y] = pos;
        this.zoomToBox(x - r, y - r, x + r, y + r, true, 0.25);
    }

    updateCrosshair() {
        const pos = this.crosshairPos;
        if (!pos) return;
        const [x, y] = pos;
        const arm = 10 / this.transform.k;
        // Two crosshair segments (horizontal + vertical), each as a flat
        // [x1, y1, x2, y2] segment for uploadHighlightSegments:
        this.uploadHighlightSegments([
            x - arm, y, x + arm, y,
            x, y - arm, x, y + arm,
        ]);
    }

    // Builds the highlight vertex buffer from a flat list of line segments
    // (every 4 numbers describe one segment: x1, y1, x2, y2). Each segment is
    // expanded into a quad (2 triangles, 6 vertices) so the highlight shader can
    // give it a constant pixel width regardless of zoom.
    uploadHighlightSegments(segments) {
        const gl = this.gl;
        if (!gl) return;
        const data = [];
        for (let i = 0; i + 3 < segments.length; i += 4) {
            const ax = segments[i], ay = segments[i + 1];
            const bx = segments[i + 2], by = segments[i + 3];
            // Per vertex: aPosition (2), aSegStart (2), aSegEnd (2), aSide (1).
            const push = (px, py, side) => data.push(px, py, ax, ay, bx, by, side);
            push(ax, ay, 1); push(ax, ay, -1); push(bx, by, -1);
            push(ax, ay, 1); push(bx, by, -1); push(bx, by, 1);
        }
        this.highlightNumVertices = data.length / 7;
        gl.bindBuffer(gl.ARRAY_BUFFER, this.buffers.highlightVertices);
        gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(data), gl.DYNAMIC_DRAW);
    }

    // Returns the bounding box [minX, minY, maxX, maxY] of the highlighted
    // shapes, or null if there is nothing to bound, so that callers passing
    // zoomTo=false can zoom to it later without re-uploading the buffer.
    setHighlight(shapes, zoomTo = true) {
        if (!this.gl) return null;

        const vertices = [];
        let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;

        const updateBounds = (x, y) => {
            if (x < minX) minX = x;
            if (x > maxX) maxX = x;
            if (y < minY) minY = y;
            if (y > maxY) maxY = y;
        };

        shapes.forEach(shape => {
            if (shape.type === 'box') {
                const [lx, ly, ux, uy] = shape.rect;
                vertices.push(lx, ly, ux, ly, ux, ly, ux, uy,
                             ux, uy, lx, uy, lx, uy, lx, ly);
                updateBounds(lx, ly);
                updateBounds(ux, uy);
            } else if (shape.type === 'edge') {
                vertices.push(...shape.p1, ...shape.p2);
                updateBounds(shape.p1[0], shape.p1[1]);
                updateBounds(shape.p2[0], shape.p2[1]);
            } else if (shape.type === 'edge_pair') {
                vertices.push(...shape.e1[0], ...shape.e1[1], ...shape.e2[0], ...shape.e2[1]);
                updateBounds(shape.e1[0][0], shape.e1[0][1]);
                updateBounds(shape.e1[1][0], shape.e1[1][1]);
                updateBounds(shape.e2[0][0], shape.e2[0][1]);
                updateBounds(shape.e2[1][0], shape.e2[1][1]);
            } else if (shape.type === 'poly' || shape.type === 'path') {
                for (let i = 0; i < shape.vertices.length - 1; i++) {
                    vertices.push(...shape.vertices[i], ...shape.vertices[i + 1]);
                }
                if (shape.type === 'poly' && shape.vertices.length > 2) {
                    vertices.push(...shape.vertices[shape.vertices.length - 1], ...shape.vertices[0]);
                }
                shape.vertices.forEach(v => updateBounds(v[0], v[1]));
            }
        });

        // `vertices` is a flat list of line-segment endpoint pairs (GL_LINES
        // layout). uploadHighlightSegments expands each segment into a quad.
        this.uploadHighlightSegments(vertices);

        const box = minX !== Infinity ? [minX, minY, maxX, maxY] : null;
        if (zoomTo && box) {
            this.zoomToBox(...box, true, 0.25);
        } else {
            this.drawGL();
        }
        return box;
    }

    clearHighlight() {
        this.crosshairPos = null;
        this.highlightNumVertices = 0;
        this.drawGL();
    }

    testState() {
        return {
            highlightNumVertices: this.highlightNumVertices,
        };
    }

    drawGLHighlight() {
        const gl = this.gl;
        const programInfo = this.programInfos.highlight;

        gl.useProgram(programInfo.program);
        gl.disable(gl.DEPTH_TEST);
        // MAX blend so overlapping quads (e.g. at segment joins) don't stack and
        // so the red highlight is forced on top of the underlying pixels:
        // On light backgrounds, MAX would turn red into white; plain red
        // is drawn instead.
        if (isLightBackground(this.style)) {
            gl.disable(gl.BLEND);
        } else {
            gl.enable(gl.BLEND);
            gl.blendFunc(gl.ONE, gl.ONE);
            gl.blendEquation(gl.MAX);
        }

        gl.uniformMatrix4fv(programInfo.uniformLocations.projectionMatrix, false, this.projectionMatrix);
        gl.uniformMatrix4fv(programInfo.uniformLocations.modelViewMatrix, false, mat4.create());
        gl.uniform4fv(programInfo.uniformLocations.color, [1.0, 0.0, 0.0, 1.0]);
        gl.uniform2fv(programInfo.uniformLocations.viewport, [this.width, this.height]);

        // A crosshair (highlightPos) and shape outlines (setHighlight) are never
        // shown at the same time, so crosshairPos distinguishes the two widths:
        const lineWidth = this.crosshairPos ? CROSSHAIR_LINE_WIDTH : HIGHLIGHT_LINE_WIDTH;
        gl.uniform1f(programInfo.uniformLocations.halfWidth, lineWidth / 2.0);

        const stride = 7 * 4; // 7 floats per vertex
        gl.bindBuffer(gl.ARRAY_BUFFER, this.buffers.highlightVertices);
        gl.vertexAttribPointer(programInfo.attribLocations.position, 2, gl.FLOAT, false, stride, 0);
        gl.vertexAttribPointer(programInfo.attribLocations.segStart, 2, gl.FLOAT, false, stride, 2 * 4);
        gl.vertexAttribPointer(programInfo.attribLocations.segEnd, 2, gl.FLOAT, false, stride, 4 * 4);
        gl.vertexAttribPointer(programInfo.attribLocations.side, 1, gl.FLOAT, false, stride, 6 * 4);
        gl.enableVertexAttribArray(programInfo.attribLocations.position);
        gl.enableVertexAttribArray(programInfo.attribLocations.segStart);
        gl.enableVertexAttribArray(programInfo.attribLocations.segEnd);
        gl.enableVertexAttribArray(programInfo.attribLocations.side);

        gl.drawArrays(gl.TRIANGLES, 0, this.highlightNumVertices);
    }

    drawGL() {
        if((this.width != this.canvas.width) || (this.height != this.canvas.height)) {
            this.width = this.canvas.width;
            this.height = this.canvas.height;

            this.resizeGL();
        }
        if(this.data) {
            this.updateProjectionMatrix();
            this.drawGLShapes();
            this.drawGLPost();
            this.drawGLGrid();
            this.drawGLLabels();
            if (this.crosshairPos) {
                this.updateCrosshair();
            }
            if (this.highlightNumVertices > 0) {
                this.drawGLHighlight();
            }
        }
    }

    updateLayers() {
        let allVisible = true;
        let allHidden = true;
        this.layerCheckboxes.forEach(checkbox => {
            const layerNid = Number(checkbox.name);

            if(checkbox.checked) {
                allHidden = false;
            } else {
                allVisible = false;
            }
            this.visibility.set(layerNid, checkbox.checked);
        });
        if(allVisible) {
            this.allLayerCheckbox.checked = true;
            this.allLayerCheckbox.indeterminate = false;
        } else if(allHidden) {
            this.allLayerCheckbox.checked = false;
            this.allLayerCheckbox.indeterminate = false;
        } else {
            this.allLayerCheckbox.indeterminate = true;
        }
        this.drawGL();
    }
};
