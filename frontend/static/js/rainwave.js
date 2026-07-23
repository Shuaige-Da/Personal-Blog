(() => {
    const body = document.body;
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const backgroundHost = document.querySelector('[data-background-playlist]');
    const backgroundLayers = [...document.querySelectorAll('[data-background-index]')];
    const nextPageLink = document.querySelector('[data-page-next]');
    let activeBackground = 0;
    let navigating = false;
    let wheelLocked = false;

    const activateBackground = (index) => {
        if (!backgroundLayers.length) {
            return;
        }

        activeBackground = (index + backgroundLayers.length) % backgroundLayers.length;
        backgroundLayers.forEach((layer, layerIndex) => {
            const active = layerIndex === activeBackground;
            layer.classList.toggle('is-active', active);
            const video = layer.querySelector('video');
            if (video) {
                if (active) {
                    video.play().catch(() => {});
                } else {
                    video.pause();
                }
            }
        });
    };

    activateBackground(0);
    if (backgroundHost && backgroundLayers.length > 1 && !reducedMotion) {
        const intervalSeconds = Number(backgroundHost.dataset.backgroundInterval || '15');
        const intervalMs = Math.max(1000, intervalSeconds * 1000);
        window.setInterval(() => activateBackground(activeBackground + 1), intervalMs);
    }

    const isLocalNavigation = (anchor) => {
        if (!anchor || anchor.target || anchor.hasAttribute('download')) {
            return false;
        }
        const url = new URL(anchor.href, window.location.href);
        return url.origin === window.location.origin && url.href !== window.location.href;
    };

    const navigate = (url) => {
        if (navigating) {
            return;
        }
        navigating = true;
        if (reducedMotion) {
            window.location.assign(url);
            return;
        }
        body.classList.add('is-leaving');
        window.setTimeout(() => window.location.assign(url), 360);
    };

    document.addEventListener('click', (event) => {
        if (
            event.defaultPrevented ||
            event.button !== 0 ||
            event.metaKey ||
            event.ctrlKey ||
            event.shiftKey ||
            event.altKey
        ) {
            return;
        }
        const anchor = event.target.closest('a[href]');
        if (!isLocalNavigation(anchor)) {
            return;
        }
        event.preventDefault();
        navigate(anchor.href);
    });

    document.addEventListener('submit', (event) => {
        const submitter = event.submitter;
        const message = submitter?.dataset.confirm;
        if (message && !window.confirm(message)) {
            event.preventDefault();
        }
    });

    const interactiveTarget = (target) => (
        target.closest('input, textarea, select, button, [contenteditable="true"]')
    );

    document.addEventListener('keydown', (event) => {
        if (interactiveTarget(event.target)) {
            return;
        }
        if ((event.key === 'ArrowRight' || event.key === 'PageDown') && nextPageLink) {
            event.preventDefault();
            navigate(nextPageLink.href);
        }
    });

    window.addEventListener(
        'wheel',
        (event) => {
            if (
                wheelLocked ||
                !nextPageLink ||
                Math.abs(event.deltaY) < 80 ||
                event.target.closest('.rw-article-shell, .rw-message-list')
            ) {
                return;
            }
            const endpoint = body.dataset.endpoint;
            if (!['index', 'articles', 'links'].includes(endpoint)) {
                return;
            }
            wheelLocked = true;
            if (event.deltaY > 0) {
                navigate(nextPageLink.href);
            }
            window.setTimeout(() => {
                wheelLocked = false;
            }, 900);
        },
        { passive: true },
    );

    let touchStartX = 0;
    let touchStartY = 0;
    document.addEventListener(
        'touchstart',
        (event) => {
            const touch = event.changedTouches[0];
            touchStartX = touch.clientX;
            touchStartY = touch.clientY;
        },
        { passive: true },
    );
    document.addEventListener(
        'touchend',
        (event) => {
            if (!nextPageLink || event.target.closest('input, textarea, button, a')) {
                return;
            }
            const touch = event.changedTouches[0];
            const deltaX = touch.clientX - touchStartX;
            const deltaY = touch.clientY - touchStartY;
            if (Math.abs(deltaX) > 80 && Math.abs(deltaX) > Math.abs(deltaY) && deltaX < 0) {
                navigate(nextPageLink.href);
            }
        },
        { passive: true },
    );

    document.querySelectorAll('.rw-flash').forEach((flash, index) => {
        window.setTimeout(() => {
            flash.animate(
                [
                    { opacity: 1, transform: 'translateY(0)' },
                    { opacity: 0, transform: 'translateY(-10px)' },
                ],
                { duration: 300, fill: 'forwards' },
            );
        }, 4200 + index * 300);
    });

    const enhanceFilePickers = () => {
        document
            .querySelectorAll('.rw-admin-mode input[type="file"].form-control')
            .forEach((input, index) => {
                if (input.closest('.rw-file-picker')) {
                    return;
                }

                if (!input.id) {
                    input.id = `rw-file-input-${index + 1}`;
                }

                const compact = input.classList.contains('form-control-sm');
                const picker = document.createElement('div');
                picker.className = `rw-file-picker rw-file-picker-auto${compact ? ' rw-file-picker-compact' : ''}`;

                input.parentNode.insertBefore(picker, input);
                input.classList.remove('form-control', 'form-control-sm');
                input.classList.add('rw-file-picker-input');
                picker.appendChild(input);

                const button = document.createElement('label');
                button.className = 'rw-file-picker-button';
                button.htmlFor = input.id;
                button.innerHTML = `
                    <i class="bi bi-folder2-open" aria-hidden="true"></i>
                    <span>${input.hasAttribute('webkitdirectory') ? '选择文件夹' : '选择文件'}</span>
                `;

                const fileName = document.createElement('span');
                fileName.className = 'rw-file-picker-name';
                fileName.textContent = input.files?.[0]?.name || '尚未选择文件';

                picker.append(button, fileName);
                input.addEventListener('change', () => {
                    const files = [...(input.files || [])];
                    if (!files.length) {
                        fileName.textContent = '尚未选择文件';
                        return;
                    }
                    fileName.textContent = files.length === 1
                        ? files[0].name
                        : `已选择 ${files.length} 个文件`;
                });
            });
    };

    const closeLiquidSelects = (except = null) => {
        document.querySelectorAll('.rw-select-shell.is-open').forEach((shell) => {
            if (shell === except) {
                return;
            }
            shell.classList.remove('is-open');
            shell.style.removeProperty('--rw-select-menu-space');
            shell.querySelector('.rw-select-trigger')?.setAttribute('aria-expanded', 'false');
        });
    };

    const enhanceSelects = () => {
        const labelsByControlId = new Map(
            [...document.querySelectorAll('label[for]')].map((label) => [label.htmlFor, label]),
        );
        document.querySelectorAll('.rw-admin-mode select.form-select').forEach((select, index) => {
            if (select.closest('.rw-select-shell')) {
                return;
            }

            if (!select.id) {
                select.id = `rw-select-${index + 1}`;
            }

            const label = labelsByControlId.get(select.id);
            const shell = document.createElement('div');
            shell.className = 'rw-select-shell';
            select.parentNode.insertBefore(shell, select);
            shell.appendChild(select);
            select.classList.add('rw-select-native');
            select.tabIndex = -1;

            const trigger = document.createElement('button');
            trigger.className = 'rw-select-trigger';
            trigger.type = 'button';
            trigger.setAttribute('role', 'combobox');
            trigger.setAttribute('aria-haspopup', 'listbox');
            trigger.setAttribute('aria-expanded', 'false');
            trigger.setAttribute('aria-label', label?.textContent.trim() || '选择选项');

            const triggerLabel = document.createElement('span');
            const triggerIcon = document.createElement('i');
            triggerIcon.className = 'bi bi-chevron-down';
            triggerIcon.setAttribute('aria-hidden', 'true');
            trigger.append(triggerLabel, triggerIcon);

            const menu = document.createElement('div');
            menu.className = 'rw-select-menu';
            menu.id = `${select.id}-menu`;
            menu.setAttribute('role', 'listbox');
            trigger.setAttribute('aria-controls', menu.id);

            const optionButtons = [...select.options].map((option, optionIndex) => {
                const optionButton = document.createElement('button');
                optionButton.className = 'rw-select-option';
                optionButton.type = 'button';
                optionButton.disabled = option.disabled;
                optionButton.dataset.optionIndex = String(optionIndex);
                optionButton.setAttribute('role', 'option');
                optionButton.innerHTML = `
                    <span></span>
                    <i class="bi bi-check2" aria-hidden="true"></i>
                `;
                optionButton.querySelector('span').textContent = option.text;
                menu.appendChild(optionButton);
                return optionButton;
            });

            const sync = () => {
                const selectedIndex = Math.max(select.selectedIndex, 0);
                const selectedOption = select.options[selectedIndex];
                triggerLabel.textContent = selectedOption?.text || '';
                trigger.disabled = select.disabled;
                optionButtons.forEach((button, optionIndex) => {
                    const selected = optionIndex === selectedIndex;
                    button.classList.toggle('is-selected', selected);
                    button.setAttribute('aria-selected', String(selected));
                });
            };

            const focusEnabledOption = (startIndex, direction = 1) => {
                let optionIndex = startIndex;
                for (let step = 0; step < optionButtons.length; step += 1) {
                    optionIndex = (optionIndex + optionButtons.length) % optionButtons.length;
                    if (!optionButtons[optionIndex].disabled) {
                        optionButtons[optionIndex].focus();
                        return;
                    }
                    optionIndex += direction;
                }
            };

            const open = (focusSelected = false) => {
                if (trigger.disabled) {
                    return;
                }
                closeLiquidSelects(shell);
                shell.classList.add('is-open');
                const menuHeight = Math.ceil(menu.getBoundingClientRect().height);
                shell.style.setProperty('--rw-select-menu-space', `${menuHeight + 8}px`);
                trigger.setAttribute('aria-expanded', 'true');
                if (focusSelected) {
                    window.requestAnimationFrame(() => {
                        focusEnabledOption(Math.max(select.selectedIndex, 0));
                    });
                }
            };

            const close = (restoreFocus = false) => {
                shell.classList.remove('is-open');
                shell.style.removeProperty('--rw-select-menu-space');
                trigger.setAttribute('aria-expanded', 'false');
                if (restoreFocus) {
                    trigger.focus();
                }
            };

            trigger.addEventListener('click', () => {
                if (shell.classList.contains('is-open')) {
                    close();
                } else {
                    open();
                }
            });

            trigger.addEventListener('keydown', (event) => {
                if (['ArrowDown', 'ArrowUp', 'Enter', ' '].includes(event.key)) {
                    event.preventDefault();
                    open(true);
                }
                if (event.key === 'Escape') {
                    close();
                }
            });

            optionButtons.forEach((optionButton) => {
                optionButton.addEventListener('click', () => {
                    select.selectedIndex = Number(optionButton.dataset.optionIndex);
                    select.dispatchEvent(new Event('change', { bubbles: true }));
                    close(true);
                });

                optionButton.addEventListener('keydown', (event) => {
                    const currentIndex = Number(optionButton.dataset.optionIndex);
                    if (event.key === 'Escape') {
                        event.preventDefault();
                        close(true);
                        return;
                    }
                    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
                        event.preventDefault();
                        const direction = event.key === 'ArrowDown' ? 1 : -1;
                        focusEnabledOption(currentIndex + direction, direction);
                    }
                    if (event.key === 'Home' || event.key === 'End') {
                        event.preventDefault();
                        focusEnabledOption(event.key === 'Home' ? 0 : optionButtons.length - 1);
                    }
                });
            });

            label?.addEventListener('click', (event) => {
                event.preventDefault();
                trigger.focus();
            });
            select.addEventListener('change', sync);
            select.form?.addEventListener('reset', () => window.setTimeout(sync));

            shell.append(trigger, menu);
            sync();
        });
    };

    if (body.classList.contains('rw-admin-mode')) {
        enhanceFilePickers();
        enhanceSelects();
        document.addEventListener('click', (event) => {
            if (!event.target.closest('.rw-select-shell')) {
                closeLiquidSelects();
            }
        });
        document.addEventListener('keydown', (event) => {
            if (event.key === 'Escape') {
                closeLiquidSelects();
            }
        });
        window.addEventListener('resize', () => {
            document.querySelectorAll('.rw-select-shell.is-open').forEach((shell) => {
                const menu = shell.querySelector('.rw-select-menu');
                if (menu) {
                    const menuHeight = Math.ceil(menu.getBoundingClientRect().height);
                    shell.style.setProperty('--rw-select-menu-space', `${menuHeight + 8}px`);
                }
            });
        });
    }

    const clockHost = document.querySelector('[data-site-clock]');
    if (clockHost) {
        const display = clockHost.querySelector('[data-clock-display]');
        const style = clockHost.dataset.clockStyle || 'digital';
        const hourCycle = clockHost.dataset.clockHourCycle || '24';
        const showDate = clockHost.dataset.clockShowDate === '1';
        const timeZone = 'Asia/Shanghai';
        const pad = (value) => String(value).padStart(2, '0');
        const dateFormatter = new Intl.DateTimeFormat('zh-CN', {
            timeZone,
            year: 'numeric',
            month: '2-digit',
            day: '2-digit',
            weekday: 'long',
        });
        const partsFormatter = new Intl.DateTimeFormat('zh-CN', {
            timeZone,
            hour: 'numeric',
            minute: 'numeric',
            second: 'numeric',
            hour12: false,
        });

        const getClockParts = (date) => {
            const values = {};
            partsFormatter.formatToParts(date).forEach((part) => {
                if (part.type !== 'literal') {
                    values[part.type] = part.value;
                }
            });
            return {
                hours: Number(values.hour),
                minutes: Number(values.minute),
                seconds: Number(values.second),
                date: dateFormatter.format(date).replace(/\//g, '-'),
            };
        };

        const formatTime = ({ hours, minutes, seconds }, includeSeconds = true) => {
            if (hourCycle === '12') {
                const suffix = hours >= 12 ? 'PM' : 'AM';
                const normalizedHours = hours % 12 || 12;
                const core = `${pad(normalizedHours)}:${pad(minutes)}`;
                return `${core}${includeSeconds ? `:${pad(seconds)}` : ''} ${suffix}`;
            }
            const core = `${pad(hours)}:${pad(minutes)}`;
            return `${core}${includeSeconds ? `:${pad(seconds)}` : ''}`;
        };

        const renderAnalog = (parts) => {
            if (!display.querySelector('[data-clock-hour]')) {
                const ticks = Array.from(
                    { length: 12 },
                    (_, index) => (
                        `<span class="rw-clock-tick" style="transform: rotate(${index * 30}deg)"></span>`
                    ),
                ).join('');
                display.innerHTML = `
                    <div class="rw-clock-analog">
                        <div class="rw-clock-face">
                            ${ticks}
                            <span class="rw-clock-hand rw-clock-hand-hour" data-clock-hour></span>
                            <span class="rw-clock-hand rw-clock-hand-minute" data-clock-minute></span>
                            <span class="rw-clock-hand rw-clock-hand-second" data-clock-second></span>
                        </div>
                        <div class="rw-clock-analog-meta">
                            <div class="rw-clock-analog-time" data-clock-analog-time></div>
                            <div class="rw-clock-analog-date" data-clock-analog-date></div>
                        </div>
                    </div>
                `;
            }

            const hourRotation = ((parts.hours % 12) + parts.minutes / 60) * 30;
            const minuteRotation = (parts.minutes + parts.seconds / 60) * 6;
            const secondRotation = parts.seconds * 6;
            display.querySelector('[data-clock-hour]').style.transform =
                `translateX(-50%) rotate(${hourRotation}deg)`;
            display.querySelector('[data-clock-minute]').style.transform =
                `translateX(-50%) rotate(${minuteRotation}deg)`;
            display.querySelector('[data-clock-second]').style.transform =
                `translateX(-50%) rotate(${secondRotation}deg)`;
            display.querySelector('[data-clock-analog-time]').textContent = formatTime(parts, false);
            display.querySelector('[data-clock-analog-date]').textContent =
                showDate ? parts.date : '北京时间';
        };

        const renderClock = () => {
            if (!display) {
                return;
            }
            const parts = getClockParts(new Date());
            const fullTime = formatTime(parts);
            if (style === 'text') {
                let timeElement = display.querySelector('.rw-clock-text-main');
                if (!timeElement) {
                    display.innerHTML = `
                        <div class="rw-clock-text-main"></div>
                        ${showDate ? '<div class="rw-clock-text-sub"></div>' : ''}
                    `;
                    timeElement = display.querySelector('.rw-clock-text-main');
                }
                timeElement.textContent = `现在是北京时间 ${fullTime}`;
                const dateElement = display.querySelector('.rw-clock-text-sub');
                if (dateElement) {
                    dateElement.textContent = parts.date;
                }
                return;
            }
            if (style === 'analog') {
                renderAnalog(parts);
                return;
            }
            let timeElement = display.querySelector('.rw-clock-digital-time');
            if (!timeElement) {
                display.innerHTML = `
                    <div class="rw-clock-digital-time"></div>
                    ${showDate ? '<div class="rw-clock-digital-date"></div>' : ''}
                `;
                timeElement = display.querySelector('.rw-clock-digital-time');
            }
            timeElement.textContent = fullTime;
            const dateElement = display.querySelector('.rw-clock-digital-date');
            if (dateElement) {
                dateElement.textContent = parts.date;
            }
        };

        renderClock();
        window.setInterval(renderClock, 1000);
    }

    const articleContent = document.querySelector('[data-article-content]');
    const tocList = document.querySelector('[data-toc-list]');
    const tocEmpty = document.querySelector('[data-toc-empty]');
    if (articleContent && tocList) {
        const headings = [...articleContent.querySelectorAll('h2, h3')];
        const linkByHeading = new Map();

        if (!headings.length) {
            if (tocEmpty) {
                tocEmpty.hidden = false;
            }
        } else {
            headings.forEach((heading, index) => {
                if (!heading.id) {
                    heading.id = `article-heading-${index + 1}`;
                }

                const item = document.createElement('li');
                const link = document.createElement('a');
                link.className = 'rw-toc-link';
                link.href = `#${heading.id}`;
                link.textContent = heading.textContent.trim();
                link.dataset.tocLevel = heading.tagName === 'H3' ? '3' : '2';
                link.addEventListener('click', (event) => {
                    event.preventDefault();
                    heading.scrollIntoView({
                        behavior: reducedMotion ? 'auto' : 'smooth',
                        block: 'start',
                    });
                    window.history.replaceState(null, '', `#${heading.id}`);
                });
                item.appendChild(link);
                tocList.appendChild(item);
                linkByHeading.set(heading, link);
            });

            linkByHeading.get(headings[0])?.classList.add('is-active');
            const observer = new IntersectionObserver(
                (entries) => {
                    const visible = entries
                        .filter((entry) => entry.isIntersecting)
                        .sort((first, second) => first.boundingClientRect.top - second.boundingClientRect.top);
                    if (!visible.length) {
                        return;
                    }
                    tocList.querySelectorAll('.rw-toc-link.is-active').forEach((link) => {
                        link.classList.remove('is-active');
                    });
                    linkByHeading.get(visible[0].target)?.classList.add('is-active');
                },
                {
                    root: document.querySelector('.rw-article-shell'),
                    rootMargin: '-8% 0px -72% 0px',
                    threshold: 0,
                },
            );
            headings.forEach((heading) => observer.observe(heading));
        }
    }

    const formatAudioTime = (seconds) => {
        if (!Number.isFinite(seconds)) {
            return '--:--';
        }
        const wholeSeconds = Math.max(0, Math.floor(seconds));
        const minutes = Math.floor(wholeSeconds / 60);
        const remainder = String(wholeSeconds % 60).padStart(2, '0');
        return `${minutes}:${remainder}`;
    };

    const audioSources = [...document.querySelectorAll('audio[data-rw-audio]')];
    audioSources.forEach((audio) => {
        const player = document.createElement('div');
        player.className = 'rw-audio-player';
        player.setAttribute('data-audio-player', '');
        player.innerHTML = `
            <button class="rw-audio-button" type="button" data-audio-toggle aria-label="播放">
                <i class="bi bi-play-fill" aria-hidden="true"></i>
            </button>
            <span class="rw-audio-time" data-audio-time>0:00 / --:--</span>
            <input
                class="rw-audio-progress"
                type="range"
                min="0"
                max="1000"
                value="0"
                step="1"
                aria-label="播放进度"
                data-audio-progress
            >
            <button class="rw-audio-button" type="button" data-audio-volume aria-label="静音">
                <i class="bi bi-volume-up-fill" aria-hidden="true"></i>
            </button>
        `;

        audio.controls = false;
        audio.classList.add('is-enhanced');
        audio.insertAdjacentElement('afterend', player);

        const toggle = player.querySelector('[data-audio-toggle]');
        const toggleIcon = toggle.querySelector('i');
        const time = player.querySelector('[data-audio-time]');
        const progress = player.querySelector('[data-audio-progress]');
        const volume = player.querySelector('[data-audio-volume]');
        const volumeIcon = volume.querySelector('i');

        const update = () => {
            const ratio = audio.duration ? audio.currentTime / audio.duration : 0;
            const progressValue = Math.round(Math.min(1, Math.max(0, ratio)) * 1000);
            progress.value = String(progressValue);
            progress.style.setProperty('--rw-audio-progress', `${progressValue / 10}%`);
            time.textContent =
                `${formatAudioTime(audio.currentTime)} / ${formatAudioTime(audio.duration)}`;
            const playing = !audio.paused && !audio.ended;
            toggleIcon.className = playing ? 'bi bi-pause-fill' : 'bi bi-play-fill';
            toggle.setAttribute('aria-label', playing ? '暂停' : '播放');
            volumeIcon.className =
                audio.muted || audio.volume === 0 ? 'bi bi-volume-mute-fill' : 'bi bi-volume-up-fill';
            volume.setAttribute('aria-label', audio.muted ? '取消静音' : '静音');
        };

        toggle.addEventListener('click', () => {
            if (audio.paused) {
                audioSources.forEach((otherAudio) => {
                    if (otherAudio !== audio) {
                        otherAudio.pause();
                    }
                });
                audio.play().catch(() => {});
            } else {
                audio.pause();
            }
        });
        volume.addEventListener('click', () => {
            audio.muted = !audio.muted;
            update();
        });
        progress.addEventListener('input', () => {
            if (Number.isFinite(audio.duration)) {
                audio.currentTime = (Number(progress.value) / 1000) * audio.duration;
            }
        });
        [
            'loadedmetadata',
            'durationchange',
            'timeupdate',
            'play',
            'pause',
            'ended',
            'volumechange',
        ].forEach((eventName) => audio.addEventListener(eventName, update));
        update();
    });
})();
