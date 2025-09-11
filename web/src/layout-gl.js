// SPDX-FileCopyrightText: 2025 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

import * as d3 from "d3";
import { mat4, vec2 } from "gl-matrix";
import { generateId } from './resultviewer.js';


// See: https://github.com/mdn/dom-examples/blob/main/webgl-examples/tutorial/sample2/webgl-demo.js

const fsSource = `
    uniform highp vec4 uLayerColor;
    
    void main() {
        gl_FragColor = vec4(uLayerColor.r, uLayerColor.g, uLayerColor.b, 1.0);
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

function containsOtherPoints(vertices, A, B, C, A_idx, B_idx, C_idx) {
    for(let D_idx=0; D_idx<vertices.length; D_idx++) {
        if((D_idx == A_idx) || (D_idx == B_idx) || (D_idx == C_idx)) {
            continue;
        }
        const D = vertices[D_idx];
        if(isConvex(A, B, D) && isConvex(B, C, D) && isConvex(C, A, D)) {
            // D is inside triangle ABC.
            return true;
        }
    }
    return false;
}

function triangulatePoly(verticesOrig) {
    const vertices = [...verticesOrig]; // copy array as not to modify the original array.
    const triangles = [];
    while(vertices.length > 3) {
        let A_idx;
        let B_idx;
        let C_idx;
        let A;
        let B;
        let C;
        let isEar = false;
        for(A_idx=0; A_idx<vertices.length; A_idx++) {
            B_idx = (A_idx + 1) % vertices.length;
            C_idx = (A_idx + 2) % vertices.length;

            A = vertices[A_idx];
            B = vertices[B_idx];
            C = vertices[C_idx];
            if(!isConvex(A, B, C)) {
                continue;
            }
            if(containsOtherPoints(vertices, A, B, C, A_idx, B_idx, C_idx)) {
                continue;
            }
            isEar = true;
            break;
        }
        if(!isEar) {
            console.log("Failed to find ear!");    
        }
        triangles.push([A, B, C]);
        vertices.splice(B_idx, 1); // removes B from vertices.

    }
    if(vertices.length == 3) {
        triangles.push([vertices[0], vertices[1], vertices[2]]);
    } else {
        alert("Invalid polygon (less than 3 vertices)!");
    }
    return triangles;
}

export class LayoutGL {
    constructor(resContent) {
        this.resContent = resContent;
        this.transform = d3.zoomIdentity.scale(1e8,1e8);
        this.visibility = new Map();
        this.brightness = 60;
    }
    update(msgData) {
        this.canvas = document.createElement('canvas');
        this.canvas.classList.add('layoutFit');

        this.resContent.replaceChildren(this.canvas);

        this.gl = this.canvas.getContext("webgl2");
        if (this.gl === null) {
            alert("WebGL initialization failed!");
            return;
        }

        this.layers = msgData['layers'];

        this.initGL();
        this.loadBuffers();
        this.drawGL();

        var zoom = d3.zoom().on( 'zoom',  ({transform}) => {
            this.transform = transform;
            //this.g.attr("transform", transform);
            //console.log("zoomed", this.transform);
            this.drawGL();
        });
        d3.select(this.canvas).call( zoom ).call(zoom.transform, this.transform);

        const resizeObserver = new ResizeObserver((entries) => {
            this.canvas.width = this.canvas.clientWidth;
            this.canvas.height = this.canvas.clientHeight;
            this.drawGL();
        });
        resizeObserver.observe(this.canvas);

        const layersUl = this.createLayerList();
        this.resContent.appendChild(layersUl);

        this.updateLayers();
    }

    createLayerList() {
        const layersUl = document.createElement('ul');
        layersUl.classList.add('layerList');
        let li;
        let id;

        li = document.createElement('li');
        id = generateId()
        li.innerHTML = `
            <input type="checkbox" checked class="allLayers" id="${id}" name="all">
            <label for="${id}"><b>all</b></label> 
        `;
        layersUl.appendChild(li);
        this.layers.forEach(layer => {
            li = document.createElement('li');
            id = generateId();
            li.innerHTML = `
                <input type="checkbox" class="singleLayer" id="${id}" name="${layer.nid}">
                <label for="${id}">
                    <svg width="30px" height="15px" viewBox="0 0 2 1"><rect fill="${layer.cssColor}" width="2" height="1" /></svg>
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
        id = generateId();
        li.innerHTML=`
            <input type="range" min="1" max="100" value="${this.brightness}" class="brightness" />
        `;
        layersUl.appendChild(li);
        li.querySelector('input').oninput = (range) => {
            this.brightness = range.target.value;
            this.drawGL();
        }

        return layersUl;
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
    }

    loadBuffers() {
        const gl = this.gl;

        this.buffers = Object();
        this.buffers.polyVertices = gl.createBuffer();
        gl.bindBuffer(gl.ARRAY_BUFFER, this.buffers.polyVertices);

        const positions = [];

        this.layers.forEach(layer => {
            layer.glOffset = positions.length/2;
            layer.polys.forEach(poly => {
                const tris = triangulatePoly(poly.vertices);
                tris.forEach(tri => {
                    positions.push(tri[0][0]);
                    positions.push(tri[0][1]);
                    positions.push(tri[1][0]);
                    positions.push(tri[1][1]);
                    positions.push(tri[2][0]);
                    positions.push(tri[2][1]);
                });
            });
            layer.glVertexCount = positions.length/2 - layer.glOffset;
        });
        this.posCount = positions.length/2/3;
        gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(positions), gl.STATIC_DRAW);

        // For postprocessing: Load a screen-filling rectangle (two triangles)
        // with texture coordinates:

        this.buffers.ppVertices = gl.createBuffer();
        gl.bindBuffer(gl.ARRAY_BUFFER, this.buffers.ppVertices);
        gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([
            1, 1,
            1, -1,
            -1, -1,
            1, 1,
            -1, -1,
            -1, 1,
        ]), gl.STATIC_DRAW);

        this.buffers.ppTexCoords = gl.createBuffer();
        gl.bindBuffer(gl.ARRAY_BUFFER, this.buffers.ppTexCoords);
        gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([
            1, 1,
            1, 0,
            0, 0,
            1, 1,
            0, 0,
            0, 1,
        ]), gl.STATIC_DRAW);
    }

    drawGLLayers() {
        const gl = this.gl;
        const programInfo = this.programInfo;

        gl.useProgram(programInfo.program);

        this.intermediateTexture = gl.createTexture();
        gl.bindTexture(gl.TEXTURE_2D, this.intermediateTexture);
        gl.texImage2D(
            gl.TEXTURE_2D,
            0,
            gl.RGBA32F,
            this.canvas.width,
            this.canvas.height,
            0,
            gl.RGBA,
            gl.FLOAT,
            null
        );

        this.intermediateTextureDepth = gl.createTexture();
        gl.bindTexture(gl.TEXTURE_2D, this.intermediateTextureDepth);
        gl.texImage2D(
            gl.TEXTURE_2D,
            0,
            gl.DEPTH_COMPONENT32F,
            this.canvas.width,
            this.canvas.height,
            0,
            gl.DEPTH_COMPONENT,
            gl.FLOAT,
            null
        );

        const fb = gl.createFramebuffer();
        gl.bindFramebuffer(gl.FRAMEBUFFER, fb);
        gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.DEPTH_ATTACHMENT, gl.TEXTURE_2D, this.intermediateTextureDepth, 0);
        gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, this.intermediateTexture, 0);

        gl.enable(gl.BLEND);
        gl.blendFunc(gl.ONE, gl.ONE);
        gl.blendEquation(gl.FUNC_ADD);

        // Depth testing is used to prevent rendering multiple overlapping polys:
        gl.enable(gl.DEPTH_TEST);
        gl.depthFunc(gl.NOTEQUAL);

        gl.clearColor(0.0, 0.0, 0.0, 1.0); // Opaque black
        gl.clearDepth(1.0);

        gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);

        gl.bindBuffer(gl.ARRAY_BUFFER, this.buffers.polyVertices);
        gl.vertexAttribPointer(programInfo.attribLocations.vertexPosition, 2, gl.FLOAT, false, 0, 0);
        gl.enableVertexAttribArray(programInfo.attribLocations.vertexPosition);

        const projectionMatrix = mat4.create();
        mat4.orthoNO(projectionMatrix, 0, gl.canvas.width, gl.canvas.height, 0, -1, 1);
        mat4.translate(projectionMatrix, projectionMatrix, [this.transform.x, this.transform.y, 0]);
        mat4.scale(projectionMatrix, projectionMatrix, [this.transform.k, this.transform.k, 1]);
        gl.uniformMatrix4fv(programInfo.uniformLocations.projectionMatrix, false, projectionMatrix);
        
        const modelViewMatrix = mat4.create();
        gl.uniformMatrix4fv(programInfo.uniformLocations.modelViewMatrix, false, modelViewMatrix);

        const brightnessFactor = Math.exp((this.brightness - 80)/15);
        // Alternatively, we could do the brightness factor in postprocessing.

        this.layers.forEach(layer => {
            if(this.visibility.get(layer.nid)==false) {
                // --> draw layer if visibility is either true or undefined.
                return;
            }
            
            // In the future, layerColor could or should be an attribute, not a uniform value.
            gl.uniform4fv(programInfo.uniformLocations.layerColor, [
                // The RGB values of layerColor are added to the RGB pixel buffer by the fragment shader:
                -Math.log(1.0 - (layer.color[0]/256)) * brightnessFactor,
                -Math.log(1.0 - (layer.color[1]/256)) * brightnessFactor,
                -Math.log(1.0 - (layer.color[2]/256)) * brightnessFactor,
                // The alpha value of layerColor is used as Z value by the vertex shader to prevent coloring the same pixel for the same layer multiple times.
                layer.nid/65536,
            ]);

            gl.drawArrays(gl.TRIANGLES, layer.glOffset, layer.glVertexCount);
        });
    }

    drawGLPost() {
        const gl = this.gl;
        const programInfo = this.programInfoPost;

        gl.useProgram(programInfo.program);
        gl.disable(gl.BLEND);
        gl.disable(gl.DEPTH_TEST);

        gl.bindFramebuffer(gl.FRAMEBUFFER, null);

        gl.viewport(0, 0, gl.canvas.width, gl.canvas.height);
        
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

    drawGL() {
        this.drawGLLayers();
        this.drawGLPost();
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
