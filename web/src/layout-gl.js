// SPDX-FileCopyrightText: 2025 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

import * as d3 from "d3";
import { mat4, vec2 } from "gl-matrix";
import earcut from 'earcut';

import { generateId } from './resultviewer.js';
import { siFormat } from './siformat.js';

// See: https://github.com/mdn/dom-examples/blob/main/webgl-examples/tutorial/sample2/webgl-demo.js

const fsSource = `
    uniform highp vec4 uLayerColor;

    uniform highp float uBrightness;
    
    void main() {
        gl_FragColor = vec4(uLayerColor.r * uBrightness, uLayerColor.g * uBrightness, uLayerColor.b * uBrightness, 1.0);
    }
`;

const vsSource = `
    attribute vec4 aVertexPosition;
    uniform mat4 uModelViewMatrix;
    uniform mat4 uProjectionMatrix;
    
    uniform highp vec4 uLayerColor;

    void main() {
        vec4 pos = uProjectionMatrix * uModelViewMatrix * aVertexPosition;
        gl_Position = vec4(
            pos.x,
            pos.y,
            uLayerColor.a,
            pos.w
        );
        gl_PointSize = 2.0;
    }
`;

const fsSourcePost = `
    varying highp vec2 vTextureCoord;

    uniform sampler2D uSampler;

    void main(void) {
        highp vec4 x = texture2D(uSampler, vTextureCoord);

        gl_FragColor = vec4(
            1.0-exp(-x.r),
            1.0-exp(-x.g),
            1.0-exp(-x.b),
            1.0
        );
    }
`;

const vsSourcePost = `
    attribute vec4 aVertexPosition;
    attribute vec2 aTextureCoord;

    uniform mat4 uProjectionMatrix;
    varying highp vec2 vTextureCoord;

    void main(void) {
        gl_Position = uProjectionMatrix * aVertexPosition;
        vTextureCoord = aTextureCoord;
    }
`;

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

function initprog(gl, vsSource, fsSource) {
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

    return prog;
}

function isConvex(A, B, C) {
    const x = 0, y = 1;
    const det = (B[x]-A[x])*(C[y]-A[y]) - (C[x]-A[x])*(B[y]-A[y]);
    return det > 0;
}

function calcLayerColor(color, layerId, dampen) {
    // If dampen is true, infinite / 0xFF brightness is 'scaled away'.
    const dampenFactor = dampen?0.95:1.0;
    return [
        // The RGB values of layerColor are added to the RGB pixel buffer by the fragment shader:
        -Math.log(1.0 - (color[0] / 255.0 * dampenFactor)),
        -Math.log(1.0 - (color[1] / 255.0 * dampenFactor)),
        -Math.log(1.0 - (color[2] / 255.0 * dampenFactor)),
        // The alpha value of layerColor is used as Z value by the vertex shader to prevent coloring the same pixel for the same layer multiple times.
        // This alpha / Z values has to be between 0.0 and 1.0!
        layerId/65536,
    ];
}

export class LayoutGL {
    constructor(resContent) {
        console.log("INIT");
        this.resContent = resContent;
        this.transform = d3.zoomIdentity.scale(1e-1,1e-1);
        this.projectionMatrix = mat4.create();
        this.visibility = new Map();
        this.brightness = 60;
        this.initialZoomDone = false;

        this.canvas = document.createElement('canvas');
        this.canvas.classList.add('layoutFit');
        this.layersUl = document.createElement('ul');
        this.layersUl.classList.add('layerList');
        this.resContent.replaceChildren(
            this.canvas,
            this.layersUl
        );

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
            //this.g.attr("transform", transform);
            //console.log("zoomed", this.transform);
            this.drawGL();
        });

        d3.select(this.canvas).call(this.zoom).call(this.zoom.transform, this.transform);

        const resizeObserver = new ResizeObserver((entries) => {
            if((this.canvas.clientWidth == 0) || (this.canvas.clientHeight == 0)) {
                return;
            }
            console.log('resize', this.canvas.clientWidth, this.canvas.clientHeight);
            this.canvas.width = this.canvas.clientWidth;
            this.canvas.height = this.canvas.clientHeight;
            this.drawGL();
        });
        resizeObserver.observe(this.canvas);

        this.resContent.addEventListener("keydown", event => this.onKeydown(event));
        this.canvas.addEventListener("mousemove", event => this.onMousemove(event));
    }


    zoomFull(animate) {
        console.log("zoom full", this.data.extent);
        let lx = this.data.extent[0];
        let ly = this.data.extent[1];
        let ux = this.data.extent[2];
        let uy = this.data.extent[3];

        const pad = Math.max(ux-lx, uy-ly)*0.05; 
        lx -= pad;
        ux += pad;
        ly -= pad;
        uy += pad;

        const w = ux - lx;
        const h = uy - ly;

        const scaleX = this.canvas.width / w;
        const scaleY = this.canvas.height / h;
        const scale = Math.min(scaleX, scaleY);
        let newZoom = d3.zoomIdentity;

        newZoom.k = scale;
        newZoom.x = -(lx*newZoom.k);
        newZoom.y = (uy*newZoom.k);

        if(scaleX > scaleY) {
            // center horizontally
            newZoom.x += (this.canvas.width - w*newZoom.k)/2;
        } else {
            // center vertically
            newZoom.y += (this.canvas.height - h*newZoom.k)/2;
        }
        console.log('scale', scaleX, scaleY);

        if(animate) {
            d3.select(this.canvas).transition().duration(400).call(this.zoom.transform, newZoom);
        } else {
            d3.select(this.canvas).call(this.zoom.transform, newZoom);
        }
    }

    onKeydown(event) {
        if(event.key == "f") {
            this.zoomFull(true);
        }
    }

    onMousemove(event) {
        const pos = this.transform.invert([event.offsetX, event.offsetY]);
        const x = siFormat(pos[0], this.data.unit);
        const y = siFormat(-pos[1], this.data.unit);
        this.cursorPosLi.innerHTML = `x=${x}&nbsp;&nbsp;y=${y}`;
    }

    update(msgData) {
        this.data = msgData;

        if(!this.initialZoomDone) {
            this.zoomFull(false);
            this.initialZoomDone = true;
        }

        this.loadBuffersDynamic();
        this.updateLayerList();
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
        this.data.layers.forEach(layer => {
            li = document.createElement('li');
            id = generateId();
            let svgPath = "M0.5 0.5 L29.5 0.5 L29.5 14.5 L0.5 14.5 Z";
            if(layer.styleCrossRect) {
                svgPath += " M0.5 0.5 L29.5 14.5 M0.5 14.5 L29.5 0.5";
            }
            li.innerHTML = `
                <input type="checkbox" class="singleLayer" id="${id}" name="${layer.nid}">
                <label for="${id}">
                    <svg width="30px" height="15px" viewBox="0 0 30 15"><path style="${layer.styleCSS}" d="${svgPath}" /></svg>
                    ${layer.path}
                </label> 
            `;
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

        li = document.createElement('li');
        li.innerHTML=`
            <input type="range" min="1" max="100" value="${this.brightness}" class="brightness" />
        `;
        layersUl.appendChild(li);
        li.querySelector('input').oninput = (range) => {
            this.brightness = range.target.value;
            this.drawGL();
        }

        li = document.createElement('li');
        li.innerHTML =`x=0&nbsp;&nbsp;y=0`;
        layersUl.appendChild(li);
        this.cursorPosLi = li;
    }

    initGL() {
        const gl = this.gl;

        gl.getExtension("EXT_color_buffer_float");
        gl.getExtension("EXT_float_blend");

        const prog = initprog(gl, vsSource, fsSource);
        const progPost = initprog(gl, vsSourcePost, fsSourcePost);

        this.programInfo = {
            program: prog,
            attribLocations: {
                vertexPosition: gl.getAttribLocation(prog, "aVertexPosition"),
            },
            uniformLocations: {
                projectionMatrix: gl.getUniformLocation(prog, "uProjectionMatrix"),
                modelViewMatrix: gl.getUniformLocation(prog, "uModelViewMatrix"),
                layerColor: gl.getUniformLocation(prog, "uLayerColor"),
                brightness: gl.getUniformLocation(prog, "uBrightness"),
            },
        };

        this.programInfoPost = {
            program: progPost,
            attribLocations: {
                vertexPosition: gl.getAttribLocation(progPost, "aVertexPosition"),
                vertexTextureCoord: gl.getAttribLocation(progPost, "aTextureCoord"),
            },
            uniformLocations: {
                projectionMatrix: gl.getUniformLocation(progPost, "uProjectionMatrix"),
                sampler: gl.getUniformLocation(progPost, "uSampler"),
            },
        };

        this.intermediateTexture = gl.createTexture();
        this.intermediateTextureDepth = gl.createTexture();
        this.intermediateFramebuffer = gl.createFramebuffer();

        this.buffers = {
            // static, loaded by loadBuffersConstant:
            gridVertices: gl.createBuffer(),
            ppVertices: gl.createBuffer(),
            ppTexCoords: gl.createBuffer(),

            // dynamic, loaded by loadBuffersDynamic:
            shapeVertices: gl.createBuffer(),
        }

        this.loadBuffersConstant();

        this.width = -1;
        this.height = -1;
    }


    loadBuffersDynamic() {
        const gl = this.gl;

        // For all shapes, separate triangle (fill) and line (stroke) vertex
        // "segments" are loaded into the the shapeVertices buffer.
        // Currently, both triangle and line data is loaded into the buffer
        // irrespective of whether it is needed to render the layer.
        // This way, the data is always there, for example if something like
        // "outline on select / hover" is desired in the future.

        const shapeVertices = [];
        this.data.layers.forEach(layer => {
            layer.shapeLineVerticesOffset = shapeVertices.length/2;
            layer.polys.forEach(poly => {
                shapeVertices.push(poly.vertices[0], poly.vertices[1]);
                for(let i=2;i<poly.vertices.length-1;i+=2) {
                    shapeVertices.push(
                        // twice: first to end last line, second to start next line
                        poly.vertices[i], poly.vertices[i+1],
                        poly.vertices[i], poly.vertices[i+1],
                    );
                }
                shapeVertices.push(poly.vertices[0], poly.vertices[1]);

                if(layer.styleCrossRect && poly.vertices.length == 4*2) {
                    // Add "X" shape if styleCrossRect is enabled: 
                    shapeVertices.push(
                        poly.vertices[0], poly.vertices[1],
                        poly.vertices[4], poly.vertices[5],
                        poly.vertices[2], poly.vertices[3],
                        poly.vertices[6], poly.vertices[7],
                    );
                }
            });
            layer.shapeLineVerticesCount = shapeVertices.length/2 - layer.shapeLineVerticesOffset;
            console.log(shapeVertices.slice(
                layer.shapeLineVerticesOffset, layer.shapeLineVerticesOffset + layer.shapeLineVerticesCount));
            layer.shapeTriVerticesOffset = shapeVertices.length/2;
            layer.polys.forEach(poly => {
                const triangles = earcut(poly.vertices);
                triangles.forEach(nodeIdx => {
                    shapeVertices.push(poly.vertices[nodeIdx*2 + 0]);
                    shapeVertices.push(poly.vertices[nodeIdx*2 + 1]);
                });
            });
            layer.shapeTriVerticesCount = shapeVertices.length/2 - layer.shapeTriVerticesOffset;

        });

        gl.bindBuffer(gl.ARRAY_BUFFER, this.buffers.shapeVertices);
        gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(shapeVertices), gl.STATIC_DRAW);
    }

    loadBuffersConstant() {
        // For postprocessing: Load a screen-filling rectangle (two triangles)
        // with texture coordinates:

        const gl = this.gl;

        gl.bindBuffer(gl.ARRAY_BUFFER, this.buffers.ppVertices);
        gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([
            1, 1,
            1, -1,
            -1, -1,
            1, 1,
            -1, -1,
            -1, 1,
        ]), gl.STATIC_DRAW);

        gl.bindBuffer(gl.ARRAY_BUFFER, this.buffers.ppTexCoords);
        gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([
            1, 1,
            1, 0,
            0, 0,
            1, 1,
            0, 0,
            0, 1,
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

    drawGLLayers() {
        const gl = this.gl;
        const programInfo = this.programInfo;
        const white = [255, 255, 255];

        gl.useProgram(programInfo.program);

        gl.bindFramebuffer(gl.FRAMEBUFFER, this.intermediateFramebuffer);

        gl.enable(gl.BLEND);
        gl.blendFunc(gl.ONE, gl.ONE);
        gl.blendEquation(gl.FUNC_ADD);

        // Depth testing is used to prevent rendering multiple overlapping polys:
        gl.enable(gl.DEPTH_TEST);
        gl.depthFunc(gl.NOTEQUAL);

        gl.clearColor(0.0, 0.0, 0.0, 1.0); // Opaque black
        gl.clearDepth(1.0);

        gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);

        gl.uniformMatrix4fv(programInfo.uniformLocations.projectionMatrix, false, this.projectionMatrix);
        gl.uniformMatrix4fv(programInfo.uniformLocations.modelViewMatrix, false, mat4.create());

        const brightnessFactor = Math.exp((this.brightness - 80)/15);

        gl.bindBuffer(gl.ARRAY_BUFFER, this.buffers.shapeVertices);
        gl.vertexAttribPointer(programInfo.attribLocations.vertexPosition, 2, gl.FLOAT, false, 0, 0);
        gl.enableVertexAttribArray(programInfo.attribLocations.vertexPosition);

        gl.uniform1f(programInfo.uniformLocations.brightness, brightnessFactor);

        this.data.layers.forEach(layer => {
            if(this.visibility.get(layer.nid)==false) {
                // --> draw layer if visibility is either true or undefined.
                return;
            }

            if(layer.styleStroke) {
                gl.uniform4fv(programInfo.uniformLocations.layerColor,
                    calcLayerColor(layer.styleStroke, layer.nid, true));

                gl.drawArrays(gl.LINES, layer.shapeLineVerticesOffset, layer.shapeLineVerticesCount);
            }
            
            // In the future, layerColor could be an attribute, not a uniform value.

            if(layer.styleFill) {
                gl.uniform4fv(programInfo.uniformLocations.layerColor,
                    calcLayerColor(layer.styleFill, layer.nid, true));

                gl.drawArrays(gl.TRIANGLES, layer.shapeTriVerticesOffset, layer.shapeTriVerticesCount);
            }
        });


        // Draw grid:

        gl.bindBuffer(gl.ARRAY_BUFFER, this.buffers.gridVertices);
        gl.vertexAttribPointer(programInfo.attribLocations.vertexPosition, 2, gl.FLOAT, false, 0, 0);
        gl.enableVertexAttribArray(programInfo.attribLocations.vertexPosition);

        gl.uniform4fv(programInfo.uniformLocations.layerColor,
            calcLayerColor(white, 0, false));
        
        gl.uniformMatrix4fv(programInfo.uniformLocations.modelViewMatrix, false, this.scaleGrid());

        gl.drawArrays(gl.POINTS, 0, this.gridSize * this.gridSize);
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
        const programInfo = this.programInfoPost;

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
        gl.uniform1i(programInfo.uniformLocations.uSampler, 0);

        gl.bindBuffer(gl.ARRAY_BUFFER, this.buffers.ppVertices);
        gl.vertexAttribPointer(programInfo.attribLocations.vertexPosition, 2, gl.FLOAT, false, 0, 0);
        gl.enableVertexAttribArray(programInfo.attribLocations.vertexPosition);

        gl.bindBuffer(gl.ARRAY_BUFFER, this.buffers.ppTexCoords);
        gl.vertexAttribPointer(programInfo.attribLocations.vertexTextureCoord, 2, gl.FLOAT, false, 0, 0);
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

    drawGL() {
        if((this.width != this.canvas.width) || (this.height != this.canvas.height)) {
            this.width = this.canvas.width;
            this.height = this.canvas.height;

            this.resizeGL();    
        }
        if(this.data) {
            this.updateProjectionMatrix();
            this.drawGLLayers();
            this.drawGLPost();
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
