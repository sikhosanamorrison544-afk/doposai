/**
 * Light theme background video (background.mp4 / background.mov).
 * Browsers need MP4 (H.264); MOV is a fallback for Safari.
 */
(function () {
    'use strict';

    function isLightThemeActive() {
        return (
            document.body.classList.contains('theme-light') ||
            document.documentElement.classList.contains('theme-light')
        );
    }

    function getVideo() {
        return document.getElementById('light-theme-video');
    }

    function ensureSources(video) {
        if (!video || video.dataset.sourcesReady === '1') {
            return;
        }
        video.innerHTML = '';
        [
            { src: '/static/background.mp4', type: 'video/mp4' },
            { src: '/static/background.mov', type: 'video/quicktime' },
        ].forEach(function (spec) {
            var source = document.createElement('source');
            source.src = spec.src;
            source.type = spec.type;
            video.appendChild(source);
        });
        video.dataset.sourcesReady = '1';
    }

    function playLightThemeVideo() {
        var video = getVideo();
        if (!video) {
            return;
        }

        if (!isLightThemeActive()) {
            video.style.display = 'none';
            video.pause();
            return;
        }

        ensureSources(video);
        video.muted = true;
        video.playsInline = true;
        video.setAttribute('playsinline', '');
        video.setAttribute('webkit-playsinline', '');
        video.loop = true;
        video.style.display = 'block';

        if (video.readyState < HTMLMediaElement.HAVE_CURRENT_DATA) {
            video.load();
        }

        var tryPlay = function () {
            var p = video.play();
            if (p && typeof p.catch === 'function') {
                p.catch(function () {
                    document.addEventListener(
                        'click',
                        function once() {
                            video.play().catch(function () {});
                        },
                        { once: true }
                    );
                });
            }
        };

        if (video.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA) {
            tryPlay();
        } else {
            video.addEventListener('loadeddata', tryPlay, { once: true });
            video.addEventListener('canplay', tryPlay, { once: true });
        }
    }

    function hideLightThemeVideo() {
        var video = getVideo();
        if (!video) {
            return;
        }
        video.style.display = 'none';
        video.pause();
    }

    function onVideoError() {
        var video = getVideo();
        if (!video || !isLightThemeActive()) {
            return;
        }
        var sources = video.querySelectorAll('source');
        var failed = parseInt(video.dataset.failedSourceIndex || '0', 10);
        if (failed < sources.length - 1) {
            video.dataset.failedSourceIndex = String(failed + 1);
            video.load();
            playLightThemeVideo();
        } else {
            console.warn('Light theme background video could not be loaded');
        }
    }

    function init() {
        var video = getVideo();
        if (!video) {
            return;
        }
        ensureSources(video);
        video.addEventListener('error', onVideoError);
        if (isLightThemeActive()) {
            playLightThemeVideo();
        }
    }

    window.playLightThemeVideo = playLightThemeVideo;
    window.hideLightThemeVideo = hideLightThemeVideo;

    function watchThemeClass() {
        var sync = function () {
            if (isLightThemeActive()) {
                playLightThemeVideo();
            } else {
                hideLightThemeVideo();
            }
        };
        var obs = new MutationObserver(sync);
        obs.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] });
        if (document.body) {
            obs.observe(document.body, { attributes: true, attributeFilter: ['class'] });
        } else {
            document.addEventListener(
                'DOMContentLoaded',
                function () {
                    if (document.body) {
                        obs.observe(document.body, { attributes: true, attributeFilter: ['class'] });
                    }
                    sync();
                },
                { once: true }
            );
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function () {
            init();
            watchThemeClass();
        });
    } else {
        init();
        watchThemeClass();
    }
})();
