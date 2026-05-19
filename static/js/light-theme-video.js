/**
 * Light theme background video — uses background-web.mp4 (720p, web-optimized).
 */
(function () {
    'use strict';

    var WEB_SRC = '/static/background-web.mp4';
    var FALLBACK_SRC = '/static/background.mp4';
    var playWatchdog = null;

    function isLightThemeActive() {
        return (
            document.body.classList.contains('theme-light') ||
            document.documentElement.classList.contains('theme-light')
        );
    }

    function getVideo() {
        return document.getElementById('light-theme-video');
    }

    function configureVideoElement(video) {
        video.muted = true;
        video.defaultMuted = true;
        video.loop = true;
        video.playsInline = true;
        video.autoplay = true;
        video.preload = 'auto';
        video.setAttribute('muted', '');
        video.setAttribute('loop', '');
        video.setAttribute('playsinline', '');
        video.setAttribute('webkit-playsinline', '');
        video.setAttribute('autoplay', '');
        video.removeAttribute('poster');
    }

    function setVideoSource(video, src) {
        if (!video || video.dataset.currentSrc === src) {
            return;
        }
        video.dataset.currentSrc = src;
        video.innerHTML = '';
        video.src = src;
    }

    function tryPlay(video) {
        if (!video || !isLightThemeActive()) {
            return;
        }
        configureVideoElement(video);
        var promise = video.play();
        if (promise && typeof promise.then === 'function') {
            promise.catch(function () {
                /* Autoplay blocked until user gesture */
            });
        }
    }

    function startPlayWatchdog() {
        stopPlayWatchdog();
        playWatchdog = window.setInterval(function () {
            if (!isLightThemeActive()) {
                return;
            }
            var video = getVideo();
            if (!video) {
                return;
            }
            if (video.paused && !video.ended) {
                tryPlay(video);
            }
        }, 1500);
    }

    function stopPlayWatchdog() {
        if (playWatchdog) {
            window.clearInterval(playWatchdog);
            playWatchdog = null;
        }
    }

    function bindVideoEvents(video) {
        if (!video || video.dataset.eventsBound === '1') {
            return;
        }
        video.dataset.eventsBound = '1';

        video.addEventListener('loadeddata', function () {
            if (isLightThemeActive()) {
                tryPlay(video);
            }
        });

        video.addEventListener('canplay', function () {
            if (isLightThemeActive()) {
                tryPlay(video);
            }
        });

        video.addEventListener('ended', function () {
            video.currentTime = 0;
            tryPlay(video);
        });

        video.addEventListener('stalled', function () {
            if (isLightThemeActive()) {
                tryPlay(video);
            }
        });

        video.addEventListener('error', function () {
            if (!isLightThemeActive()) {
                return;
            }
            if (video.dataset.currentSrc !== FALLBACK_SRC) {
                setVideoSource(video, FALLBACK_SRC);
                video.load();
                tryPlay(video);
            } else if (video.dataset.currentSrc !== '/static/background.mov') {
                setVideoSource(video, '/static/background.mov');
                video.load();
                tryPlay(video);
            } else {
                console.warn('Light theme background video failed to load');
            }
        });

        document.addEventListener('visibilitychange', function () {
            if (document.visibilityState === 'visible' && isLightThemeActive()) {
                tryPlay(video);
            }
        });

        document.addEventListener(
            'click',
            function resumeOnGesture() {
                if (isLightThemeActive()) {
                    tryPlay(video);
                }
            },
            { capture: true, passive: true }
        );
    }

    function playLightThemeVideo() {
        var video = getVideo();
        if (!video) {
            return;
        }

        if (!isLightThemeActive()) {
            hideLightThemeVideo();
            return;
        }

        bindVideoEvents(video);
        if (!video.dataset.currentSrc) {
            setVideoSource(video, WEB_SRC);
        }

        video.style.display = 'block';
        video.style.visibility = 'visible';

        if (video.readyState >= HTMLMediaElement.HAVE_METADATA) {
            tryPlay(video);
        } else {
            video.load();
        }

        startPlayWatchdog();
    }

    function hideLightThemeVideo() {
        stopPlayWatchdog();
        var video = getVideo();
        if (!video) {
            return;
        }
        video.pause();
        video.style.display = 'none';
    }

    function init() {
        var video = getVideo();
        if (!video) {
            return;
        }
        bindVideoEvents(video);
        if (isLightThemeActive()) {
            playLightThemeVideo();
        }
    }

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
        }
    }

    window.playLightThemeVideo = playLightThemeVideo;
    window.hideLightThemeVideo = hideLightThemeVideo;

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
