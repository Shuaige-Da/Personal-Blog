(() => {
    'use strict';

    const GLASS_SELECTOR = [
        '[data-liquid-glass]',
        '.rw-body[data-ui-theme="liquid_ios"] .rw-hologlass',
        '.rw-body[data-ui-theme="liquid_ios"] .rw-recent-strip',
        '.rw-body[data-ui-theme="liquid_ios"] .rw-pagination',
        '.rw-body[data-ui-theme="liquid_ios"] .rw-primary-button',
        '.rw-body[data-ui-theme="liquid_ios"] .rw-flash',
        '.rw-body[data-ui-theme="liquid_ios"] .rw-audio-player',
    ].join(',');
    const REDUCED_MOTION = window.matchMedia('(prefers-reduced-motion: reduce)');
    const MAX_SURFACES = 24;

    const clamp = (value, min, max) => Math.min(max, Math.max(min, value));

    function addMaterialLayers(surface) {
        if (surface.dataset.liquidReady === 'true') return;
        surface.dataset.liquidReady = 'true';
        surface.classList.add('lg-glass');
        if (!surface.dataset.glassShape) {
            surface.dataset.glassShape = getComputedStyle(surface).borderRadius === '50%'
                ? 'circle'
                : 'panel';
        }
        if (!surface.dataset.glassDepth) surface.dataset.glassDepth = '0.58';

        ['edge', 'specular', 'noise'].forEach((name) => {
            const layer = document.createElement('span');
            layer.className = `lg-glass-layer lg-glass-layer--${name}`;
            layer.setAttribute('aria-hidden', 'true');
            surface.appendChild(layer);
        });
    }

    class PointerOptics {
        constructor(surfaces) {
            this.items = surfaces.map((surface) => ({
                surface,
                x: 0.5,
                y: 0.18,
                tx: 0.5,
                ty: 0.18,
                vx: 0,
                vy: 0,
            }));
            this.raf = 0;
            this.visible = !document.hidden;
            this.bind();
            this.tick = this.tick.bind(this);
            this.raf = requestAnimationFrame(this.tick);
        }

        bind() {
            this.items.forEach((item) => {
                const { surface } = item;
                surface.addEventListener('pointerenter', () => surface.classList.add('is-lg-hovered'));
                surface.addEventListener('pointermove', (event) => {
                    const rect = surface.getBoundingClientRect();
                    item.tx = clamp((event.clientX - rect.left) / rect.width, 0, 1);
                    item.ty = clamp((event.clientY - rect.top) / rect.height, 0, 1);
                });
                surface.addEventListener('pointerleave', () => {
                    surface.classList.remove('is-lg-hovered');
                    item.tx = 0.5;
                    item.ty = 0.18;
                });
                surface.addEventListener('pointerdown', (event) => {
                    surface.classList.remove('is-lg-released');
                    surface.classList.add('is-lg-pressed');
                    if (surface.setPointerCapture) surface.setPointerCapture(event.pointerId);
                });
                const release = () => {
                    if (!surface.classList.contains('is-lg-pressed')) return;
                    surface.classList.remove('is-lg-pressed');
                    surface.classList.add('is-lg-released');
                    window.setTimeout(() => surface.classList.remove('is-lg-released'), 560);
                };
                surface.addEventListener('pointerup', release);
                surface.addEventListener('pointercancel', release);
                surface.addEventListener('lostpointercapture', release);
                surface.addEventListener('keydown', (event) => {
                    if (event.key === ' ' || event.key === 'Enter') {
                        surface.classList.add('is-lg-pressed');
                    }
                });
                surface.addEventListener('keyup', (event) => {
                    if (event.key === ' ' || event.key === 'Enter') release();
                });
            });
            document.addEventListener('visibilitychange', () => {
                this.visible = !document.hidden;
                if (this.visible && !this.raf) this.raf = requestAnimationFrame(this.tick);
            });
        }

        tick() {
            this.raf = 0;
            if (!this.visible) return;
            const stiffness = REDUCED_MOTION.matches ? 1 : 0.14;
            const damping = 0.74;
            this.items.forEach((item) => {
                item.vx = (item.vx + (item.tx - item.x) * stiffness) * damping;
                item.vy = (item.vy + (item.ty - item.y) * stiffness) * damping;
                item.x += item.vx;
                item.y += item.vy;
                item.surface.style.setProperty('--lg-pointer-x', `${(item.x * 100).toFixed(2)}%`);
                item.surface.style.setProperty('--lg-pointer-y', `${(item.y * 100).toFixed(2)}%`);
                item.surface.style.setProperty('--lg-normal-x', (item.x - 0.5).toFixed(3));
                item.surface.style.setProperty('--lg-normal-y', (item.y - 0.5).toFixed(3));
            });
            this.raf = requestAnimationFrame(this.tick);
        }
    }

    class LiquidRefractionRenderer {
        constructor(canvas, surfaces) {
            this.canvas = canvas;
            this.surfaces = surfaces.filter((surface) => !surface.closest('[hidden]')).slice(0, MAX_SURFACES);
            this.source = document.querySelector('[data-liquid-refraction-source]')
                || document.querySelector('.rw-background.is-active img, .rw-background.is-active video');
            this.gl = null;
            this.ctx = null;
            this.program = null;
            this.texture = null;
            this.lastFrame = 0;
            this.visible = !document.hidden;
            this.mode = 'css';
            this.frame = this.frame.bind(this);
            this.handleVisibility = this.handleVisibility.bind(this);
        }

        start() {
            if (!this.canvas || !this.source) {
                document.documentElement.classList.add('lg-css-fallback');
                this.reportQuality('CSS 多层');
                return;
            }

            try {
                this.gl = this.canvas.getContext('webgl', {
                    alpha: true,
                    antialias: false,
                    premultipliedAlpha: true,
                    powerPreference: 'high-performance',
                });
                if (this.gl) this.initWebGL();
            } catch (error) {
                this.gl = null;
            }

            if (!this.gl) {
                this.ctx = this.canvas.getContext('2d', { alpha: true });
                if (this.ctx) {
                    this.mode = 'canvas';
                    document.documentElement.classList.add('lg-webgl-fallback');
                    this.reportQuality('Canvas 2D');
                } else {
                    document.documentElement.classList.add('lg-css-fallback');
                    this.reportQuality('CSS 多层');
                    return;
                }
            }

            window.addEventListener('resize', () => this.resize(), { passive: true });
            document.addEventListener('visibilitychange', this.handleVisibility);
            this.resize();
            requestAnimationFrame(this.frame);
        }

        initWebGL() {
            const gl = this.gl;
            const vertex = `
                attribute vec2 aPosition;
                void main() { gl_Position = vec4(aPosition, 0.0, 1.0); }
            `;
            const fragment = `
                precision mediump float;
                uniform sampler2D uTexture;
                uniform vec2 uResolution;
                uniform vec4 uCover;
                uniform int uCount;
                uniform vec4 uRects[${MAX_SURFACES}];
                uniform vec2 uParams[${MAX_SURFACES}];
                uniform float uRefraction;

                float roundedMask(vec2 p, vec2 halfSize, float radius) {
                    vec2 q = abs(p) - halfSize + radius;
                    float d = length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - radius;
                    return 1.0 - smoothstep(-1.2, 1.4, d);
                }

                vec4 sampleScene(vec2 screenPoint) {
                    vec2 uv = (screenPoint - uCover.xy) / uCover.zw;
                    uv.y = 1.0 - uv.y;
                    return texture2D(uTexture, clamp(uv, 0.001, 0.999));
                }

                void main() {
                    vec2 screenPoint = vec2(gl_FragCoord.x, uResolution.y - gl_FragCoord.y);
                    vec4 result = vec4(0.0);
                    for (int i = 0; i < ${MAX_SURFACES}; i++) {
                        if (i >= uCount) break;
                        vec4 rect = uRects[i];
                        vec2 halfSize = rect.zw * 0.5;
                        vec2 center = rect.xy + halfSize;
                        vec2 local = screenPoint - center;
                        float radius = min(uParams[i].y, min(halfSize.x, halfSize.y));
                        float mask = roundedMask(local, halfSize, radius);
                        if (mask > 0.001) {
                            vec2 normalized = local / max(halfSize, vec2(1.0));
                            float radial = clamp(length(normalized), 0.0, 1.42);
                            float edge = smoothstep(0.38, 1.02, radial);
                            vec2 normal = normalize(local + vec2(0.001));
                            float depth = uParams[i].x * uRefraction;
                            vec2 magnified = center + local * (0.978 - depth * 0.012);
                            vec2 bent = magnified - normal * edge * edge * (7.0 + depth * 15.0);
                            bent.x += normal.y * edge * 1.8 * depth;
                            vec2 chroma = normal * edge * (0.65 + depth * 1.15);
                            vec4 base = sampleScene(bent);
                            float red = sampleScene(bent + chroma).r;
                            float blue = sampleScene(bent - chroma).b;
                            vec3 refracted = vec3(red, base.g, blue);
                            float topLight = smoothstep(0.36, -0.96, normalized.y) * edge;
                            float bottomShade = smoothstep(0.25, 1.0, normalized.y) * edge;
                            refracted += vec3(0.12, 0.18, 0.23) * topLight;
                            refracted -= vec3(0.08, 0.06, 0.035) * bottomShade;
                            result = vec4(refracted, mask * (0.55 + edge * 0.25));
                        }
                    }
                    gl_FragColor = result;
                }
            `;
            const compile = (type, source) => {
                const shader = gl.createShader(type);
                gl.shaderSource(shader, source);
                gl.compileShader(shader);
                if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
                    throw new Error(gl.getShaderInfoLog(shader));
                }
                return shader;
            };
            const program = gl.createProgram();
            gl.attachShader(program, compile(gl.VERTEX_SHADER, vertex));
            gl.attachShader(program, compile(gl.FRAGMENT_SHADER, fragment));
            gl.linkProgram(program);
            if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
                throw new Error(gl.getProgramInfoLog(program));
            }
            gl.useProgram(program);
            this.program = program;
            const buffer = gl.createBuffer();
            gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
            gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
            const position = gl.getAttribLocation(program, 'aPosition');
            gl.enableVertexAttribArray(position);
            gl.vertexAttribPointer(position, 2, gl.FLOAT, false, 0, 0);
            this.texture = gl.createTexture();
            gl.bindTexture(gl.TEXTURE_2D, this.texture);
            gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
            gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
            gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
            gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
            gl.enable(gl.BLEND);
            gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
            this.mode = 'webgl';
            this.reportQuality('WebGL 实时');
        }

        reportQuality(label) {
            document.querySelectorAll('[data-liquid-quality]').forEach((node) => {
                node.textContent = label;
            });
        }

        handleVisibility() {
            this.visible = !document.hidden;
            if (this.visible) requestAnimationFrame(this.frame);
        }

        resize() {
            const dprLimit = window.innerWidth < 720 ? 1 : 1.5;
            const dpr = Math.min(window.devicePixelRatio || 1, dprLimit);
            const width = Math.max(1, Math.round(window.innerWidth * dpr));
            const height = Math.max(1, Math.round(window.innerHeight * dpr));
            if (this.canvas.width !== width || this.canvas.height !== height) {
                this.canvas.width = width;
                this.canvas.height = height;
            }
        }

        sourceDimensions() {
            const width = this.source.videoWidth || this.source.naturalWidth || this.source.width;
            const height = this.source.videoHeight || this.source.naturalHeight || this.source.height;
            return { width, height };
        }

        coverRect() {
            const source = this.sourceDimensions();
            if (!source.width || !source.height) return null;
            const viewport = { width: window.innerWidth, height: window.innerHeight };
            const scale = Math.max(viewport.width / source.width, viewport.height / source.height);
            const width = source.width * scale;
            const height = source.height * scale;
            const objectPositionX = this.source.matches('[data-liquid-refraction-source]') ? 0.58 : 0.5;
            return {
                x: (viewport.width - width) * objectPositionX,
                y: (viewport.height - height) * 0.5,
                width,
                height,
            };
        }

        activeSurfaces() {
            return Array.from(document.querySelectorAll(GLASS_SELECTOR))
                .filter((surface) => {
                    const rect = surface.getBoundingClientRect();
                    return !surface.closest('[hidden]') && rect.width > 18 && rect.height > 18
                        && rect.bottom > 0 && rect.top < window.innerHeight;
                })
                .slice(0, MAX_SURFACES);
        }

        geometry() {
            const dpr = this.canvas.width / window.innerWidth;
            const rects = new Float32Array(MAX_SURFACES * 4);
            const params = new Float32Array(MAX_SURFACES * 2);
            const active = this.activeSurfaces();
            active.forEach((surface, index) => {
                const rect = surface.getBoundingClientRect();
                rects.set([rect.left * dpr, rect.top * dpr, rect.width * dpr, rect.height * dpr], index * 4);
                const computedRadius = parseFloat(getComputedStyle(surface).borderTopLeftRadius) || 24;
                const depth = parseFloat(surface.dataset.glassDepth || '0.58');
                params.set([depth, computedRadius * dpr], index * 2);
            });
            return { active, rects, params, dpr };
        }

        renderWebGL() {
            const gl = this.gl;
            const cover = this.coverRect();
            if (!cover) return;
            const geometry = this.geometry();
            gl.viewport(0, 0, this.canvas.width, this.canvas.height);
            gl.clearColor(0, 0, 0, 0);
            gl.clear(gl.COLOR_BUFFER_BIT);
            gl.useProgram(this.program);
            try {
                gl.bindTexture(gl.TEXTURE_2D, this.texture);
                gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
                gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, this.source);
            } catch (error) {
                return;
            }
            const uniform = (name) => gl.getUniformLocation(this.program, name);
            gl.uniform1i(uniform('uTexture'), 0);
            gl.uniform2f(uniform('uResolution'), this.canvas.width, this.canvas.height);
            gl.uniform4f(
                uniform('uCover'),
                cover.x * geometry.dpr,
                cover.y * geometry.dpr,
                cover.width * geometry.dpr,
                cover.height * geometry.dpr,
            );
            gl.uniform1i(uniform('uCount'), geometry.active.length);
            gl.uniform4fv(uniform('uRects[0]'), geometry.rects);
            gl.uniform2fv(uniform('uParams[0]'), geometry.params);
            const refraction = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--lg-refraction')) || 0.72;
            gl.uniform1f(uniform('uRefraction'), REDUCED_MOTION.matches ? Math.min(refraction, 0.38) : refraction);
            gl.drawArrays(gl.TRIANGLES, 0, 3);
        }

        roundedPath(ctx, rect, radius) {
            const r = Math.min(radius, rect.width / 2, rect.height / 2);
            ctx.beginPath();
            if (ctx.roundRect) ctx.roundRect(rect.left, rect.top, rect.width, rect.height, r);
            else ctx.rect(rect.left, rect.top, rect.width, rect.height);
        }

        drawCoveredSource(ctx, cover) {
            ctx.drawImage(this.source, cover.x, cover.y, cover.width, cover.height);
        }

        renderCanvas() {
            const ctx = this.ctx;
            const cover = this.coverRect();
            if (!cover) return;
            const dpr = this.canvas.width / window.innerWidth;
            ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
            ctx.clearRect(0, 0, window.innerWidth, window.innerHeight);
            this.activeSurfaces().forEach((surface) => {
                const rect = surface.getBoundingClientRect();
                const radius = parseFloat(getComputedStyle(surface).borderTopLeftRadius) || 24;
                const depth = parseFloat(surface.dataset.glassDepth || '0.58');
                ctx.save();
                this.roundedPath(ctx, rect, radius);
                ctx.clip();
                ctx.translate(rect.left + rect.width / 2, rect.top + rect.height / 2);
                const scale = 1.012 + depth * 0.018;
                ctx.scale(scale, scale);
                ctx.translate(-(rect.left + rect.width / 2), -(rect.top + rect.height / 2));
                ctx.globalAlpha = 0.7;
                this.drawCoveredSource(ctx, cover);
                ctx.restore();
                ctx.save();
                this.roundedPath(ctx, rect, radius);
                ctx.strokeStyle = 'rgba(225,245,255,.45)';
                ctx.lineWidth = 1.2;
                ctx.stroke();
                ctx.restore();
            });
        }

        frame(time) {
            if (!this.visible) return;
            const isVideo = this.source instanceof HTMLVideoElement;
            const interval = REDUCED_MOTION.matches ? 110 : (isVideo ? 33 : 50);
            if (time - this.lastFrame >= interval) {
                this.lastFrame = time;
                if (this.mode === 'webgl') this.renderWebGL();
                else if (this.mode === 'canvas') this.renderCanvas();
            }
            requestAnimationFrame(this.frame);
        }
    }

    function boot() {
        const surfaces = Array.from(document.querySelectorAll(GLASS_SELECTOR));
        surfaces.forEach(addMaterialLayers);
        new PointerOptics(surfaces);
        const renderer = new LiquidRefractionRenderer(
            document.querySelector('[data-liquid-refraction-canvas]'),
            surfaces,
        );
        renderer.start();
        window.addEventListener('pageshow', () => renderer.resize());
    }

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot, { once: true });
    else boot();
})();
