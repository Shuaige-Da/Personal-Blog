(() => {
    'use strict';

    const lab = document.querySelector('[data-glass-lab]');
    if (!lab) return;

    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
    const clamp = (value, min, max) => Math.min(max, Math.max(min, value));

    function setupSelect() {
        const root = lab.querySelector('[data-liquid-select]');
        if (!root) return;
        const trigger = root.querySelector('.lg-select-trigger');
        const menu = root.querySelector('.lg-select-menu');
        const options = Array.from(root.querySelectorAll('[role="option"]'));
        const label = root.querySelector('[data-liquid-select-label]');
        let activeIndex = options.findIndex((option) => option.classList.contains('is-selected'));

        const setOpen = (open, focusOption = false) => {
            root.classList.toggle('is-open', open);
            trigger.setAttribute('aria-expanded', String(open));
            menu.hidden = !open;
            if (open && focusOption) options[Math.max(0, activeIndex)].focus();
        };
        const select = (option) => {
            activeIndex = options.indexOf(option);
            options.forEach((candidate) => {
                const selected = candidate === option;
                candidate.classList.toggle('is-selected', selected);
                candidate.setAttribute('aria-selected', String(selected));
            });
            label.textContent = option.querySelector('span').textContent;
            lab.dataset.palette = option.dataset.value;
            setOpen(false);
            trigger.focus();
        };

        trigger.addEventListener('click', () => setOpen(menu.hidden, true));
        trigger.addEventListener('keydown', (event) => {
            if (['ArrowDown', 'ArrowUp', 'Enter', ' '].includes(event.key)) {
                event.preventDefault();
                setOpen(true, true);
            }
        });
        options.forEach((option, index) => {
            option.addEventListener('click', () => select(option));
            option.addEventListener('keydown', (event) => {
                if (event.key === 'Escape') {
                    event.preventDefault();
                    setOpen(false);
                    trigger.focus();
                } else if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault();
                    select(option);
                } else if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
                    event.preventDefault();
                    const direction = event.key === 'ArrowDown' ? 1 : -1;
                    options[(index + direction + options.length) % options.length].focus();
                }
            });
        });
        document.addEventListener('pointerdown', (event) => {
            if (!root.contains(event.target)) setOpen(false);
        });
    }

    function setupSwitch() {
        const control = lab.querySelector('[data-liquid-switch]');
        if (!control) return;
        const toggle = () => {
            const enabled = control.getAttribute('aria-checked') !== 'true';
            control.setAttribute('aria-checked', String(enabled));
            lab.classList.toggle('is-optics-paused', !enabled);
            document.documentElement.style.setProperty('--lg-refraction', enabled ? '0.72' : '0.26');
        };
        control.addEventListener('click', toggle);
        control.addEventListener('keydown', (event) => {
            if ((event.key === ' ' || event.key === 'Enter') && event.detail === 0) {
                event.preventDefault();
                toggle();
            }
        });
    }

    function setupActions() {
        lab.querySelectorAll('[data-liquid-action]').forEach((button) => {
            button.addEventListener('click', () => {
                button.classList.toggle('is-active');
                button.setAttribute('aria-pressed', String(button.classList.contains('is-active')));
            });
        });
        const play = lab.querySelector('[data-liquid-play]');
        if (play) {
            play.addEventListener('click', () => {
                play.classList.remove('is-playing');
                void play.offsetWidth;
                play.classList.add('is-playing');
                play.setAttribute('aria-label', '折射波动画已播放');
                window.setTimeout(() => {
                    play.classList.remove('is-playing');
                    play.setAttribute('aria-label', '播放折射波动画');
                }, reducedMotion.matches ? 80 : 860);
            });
        }
    }

    function setupNavigation() {
        const items = Array.from(lab.querySelectorAll('[data-liquid-nav-item]'));
        const indicator = lab.querySelector('[data-liquid-nav-indicator]');
        const update = (index) => {
            items.forEach((item, candidateIndex) => {
                item.classList.toggle('is-active', candidateIndex === index);
                item.setAttribute('aria-current', candidateIndex === index ? 'page' : 'false');
            });
            if (indicator) indicator.style.transform = `translateX(${index * 100}%)`;
        };
        items.forEach((item, index) => item.addEventListener('click', () => update(index)));
        const initial = Math.max(0, items.findIndex((item) => item.classList.contains('is-active')));
        update(initial);
    }

    function setupSettings() {
        const panel = lab.querySelector('[data-lab-settings]');
        const toggle = lab.querySelector('[data-lab-settings-toggle]');
        const close = lab.querySelector('[data-lab-settings-close]');
        if (!panel || !toggle) return;
        const setOpen = (open) => {
            panel.hidden = !open;
            toggle.setAttribute('aria-expanded', String(open));
            if (open) panel.querySelector('button, input')?.focus();
            else toggle.focus();
        };
        toggle.addEventListener('click', () => setOpen(panel.hidden));
        close?.addEventListener('click', () => setOpen(false));
        panel.addEventListener('keydown', (event) => {
            if (event.key === 'Escape') setOpen(false);
        });
        lab.querySelectorAll('[data-lab-scene]').forEach((button) => {
            button.addEventListener('click', () => {
                lab.dataset.scene = button.dataset.labScene;
                lab.querySelectorAll('[data-lab-scene]').forEach((candidate) => {
                    candidate.classList.toggle('is-active', candidate === button);
                });
            });
        });
        const controls = {
            refraction: (value) => document.documentElement.style.setProperty('--lg-refraction', (value / 100).toFixed(2)),
            blur: (value) => document.documentElement.style.setProperty('--lg-blur', `${value}px`),
            opacity: (value) => document.documentElement.style.setProperty('--lg-opacity', (value / 100).toFixed(2)),
        };
        lab.querySelectorAll('[data-lab-control]').forEach((input) => {
            input.addEventListener('input', () => {
                const name = input.dataset.labControl;
                controls[name]?.(Number(input.value));
                const output = lab.querySelector(`[data-lab-output="${name}"]`);
                if (output) output.value = input.value;
            });
        });
    }

    class CanvasMagnifier {
        constructor() {
            this.source = lab.querySelector('[data-liquid-lens-source]');
            this.output = lab.querySelector('[data-liquid-lens-output]');
            this.lens = lab.querySelector('[data-liquid-lens]');
            this.container = lab.querySelector('.lg-lens-demo');
            this.sourceContext = this.source?.getContext('2d');
            this.outputContext = this.output?.getContext('2d');
            this.position = { x: 0.5, y: 0.5 };
            this.target = { x: 0.5, y: 0.5 };
            this.velocity = { x: 0, y: 0 };
            this.dragging = false;
            this.frame = this.frame.bind(this);
        }

        start() {
            if (!this.sourceContext || !this.outputContext || !this.lens || !this.container) return;
            this.resize();
            window.addEventListener('resize', () => this.resize(), { passive: true });
            this.lens.addEventListener('pointerdown', (event) => {
                this.dragging = true;
                this.lens.setPointerCapture(event.pointerId);
                this.moveTarget(event.clientX, event.clientY);
            });
            this.lens.addEventListener('pointermove', (event) => {
                if (this.dragging) this.moveTarget(event.clientX, event.clientY);
            });
            const stop = () => { this.dragging = false; };
            this.lens.addEventListener('pointerup', stop);
            this.lens.addEventListener('pointercancel', stop);
            this.lens.addEventListener('keydown', (event) => {
                const step = event.shiftKey ? 0.08 : 0.035;
                if (event.key === 'ArrowLeft') this.target.x -= step;
                else if (event.key === 'ArrowRight') this.target.x += step;
                else if (event.key === 'ArrowUp') this.target.y -= step;
                else if (event.key === 'ArrowDown') this.target.y += step;
                else return;
                event.preventDefault();
                this.target.x = clamp(this.target.x, 0.17, 0.83);
                this.target.y = clamp(this.target.y, 0.24, 0.76);
            });
            requestAnimationFrame(this.frame);
        }

        moveTarget(clientX, clientY) {
            const rect = this.container.getBoundingClientRect();
            this.target.x = clamp((clientX - rect.left) / rect.width, 0.17, 0.83);
            this.target.y = clamp((clientY - rect.top) / rect.height, 0.24, 0.76);
        }

        resize() {
            const dpr = Math.min(window.devicePixelRatio || 1, 2);
            const rect = this.container.getBoundingClientRect();
            this.source.width = Math.max(1, Math.round(rect.width * dpr));
            this.source.height = Math.max(1, Math.round(rect.height * dpr));
            const lensRect = this.lens.getBoundingClientRect();
            this.output.width = Math.max(1, Math.round(lensRect.width * dpr));
            this.output.height = Math.max(1, Math.round(lensRect.height * dpr));
            this.drawSource();
        }

        drawSource() {
            const ctx = this.sourceContext;
            const width = this.source.width;
            const height = this.source.height;
            const gradient = ctx.createLinearGradient(0, 0, width, height);
            gradient.addColorStop(0, '#071120');
            gradient.addColorStop(0.54, '#101a29');
            gradient.addColorStop(1, '#06101e');
            ctx.fillStyle = gradient;
            ctx.fillRect(0, 0, width, height);
            ctx.fillStyle = 'rgba(113, 207, 255, .07)';
            ctx.fillRect(0, 0, width, height * 0.19);
            const scale = width / 940;
            const lineHeight = 24 * scale;
            const fontSize = 15 * scale;
            ctx.font = `${fontSize}px ui-monospace, SFMono-Regular, Consolas, monospace`;
            const lines = [
                ['# RainWave / optical material probe', '#65d3ff'],
                ['$ render --theme liquid_ios --quality adaptive', '#eef8ff'],
                ['sampling background …  edge normals ready', '#a8bbc9'],
                ['refraction 0.72   dispersion 0.018   blur 18px', '#d5acff'],
                ['top highlight +0.18   bottom absorption -0.12', '#ffc982'],
                ['WebGL surface linked · drag the lens to inspect', '#7ee2bd'],
                ['The text behind this lens is sampled from one canvas.', '#eef8ff'],
            ];
            lines.forEach(([text, color], index) => {
                ctx.fillStyle = color;
                ctx.fillText(text, 34 * scale, (36 * scale) + lineHeight * index);
            });
            ctx.strokeStyle = 'rgba(160, 220, 255, .08)';
            ctx.lineWidth = Math.max(1, scale);
            for (let x = 0; x < width; x += 42 * scale) {
                ctx.beginPath();
                ctx.moveTo(x, 0);
                ctx.lineTo(x, height);
                ctx.stroke();
            }
        }

        drawLens() {
            const ctx = this.outputContext;
            const sourceWidth = this.source.width;
            const sourceHeight = this.source.height;
            const outputWidth = this.output.width;
            const outputHeight = this.output.height;
            const zoom = 1.28;
            const sampleWidth = outputWidth / zoom;
            const sampleHeight = outputHeight / zoom;
            const centerX = this.position.x * sourceWidth;
            const centerY = this.position.y * sourceHeight;
            const sampleX = clamp(centerX - sampleWidth / 2, 0, sourceWidth - sampleWidth);
            const sampleY = clamp(centerY - sampleHeight / 2, 0, sourceHeight - sampleHeight);
            ctx.clearRect(0, 0, outputWidth, outputHeight);
            ctx.save();
            ctx.filter = 'saturate(1.12) contrast(1.04)';
            ctx.drawImage(this.source, sampleX, sampleY, sampleWidth, sampleHeight, 0, 0, outputWidth, outputHeight);
            ctx.restore();
            const sheen = ctx.createLinearGradient(0, 0, 0, outputHeight);
            sheen.addColorStop(0, 'rgba(255,255,255,.16)');
            sheen.addColorStop(0.35, 'rgba(255,255,255,.025)');
            sheen.addColorStop(1, 'rgba(3,15,31,.14)');
            ctx.fillStyle = sheen;
            ctx.fillRect(0, 0, outputWidth, outputHeight);
        }

        frame() {
            const stiffness = reducedMotion.matches ? 1 : (this.dragging ? 0.25 : 0.115);
            const damping = reducedMotion.matches ? 0 : 0.72;
            this.velocity.x = (this.velocity.x + (this.target.x - this.position.x) * stiffness) * damping;
            this.velocity.y = (this.velocity.y + (this.target.y - this.position.y) * stiffness) * damping;
            this.position.x += this.velocity.x;
            this.position.y += this.velocity.y;
            this.lens.style.left = `${(this.position.x * 100).toFixed(2)}%`;
            this.lens.style.top = `${(this.position.y * 100).toFixed(2)}%`;
            this.lens.style.transform = 'translate(-50%, -50%)';
            this.drawLens();
            if (!document.hidden) requestAnimationFrame(this.frame);
            else document.addEventListener('visibilitychange', () => requestAnimationFrame(this.frame), { once: true });
        }
    }

    setupSelect();
    setupSwitch();
    setupActions();
    setupNavigation();
    setupSettings();
    new CanvasMagnifier().start();
})();
