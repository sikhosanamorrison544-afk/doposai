/**
 * 3D Background for Default Theme
 * Loads and renders butterflies.glb model to enhance glassmorphism
 */

(function() {
    'use strict';
    
    let scene, camera, renderer, model;
    let animationId = null;
    let isDefaultTheme = false;
    let modelLoaded = false;
    let loaderReady = false;
    let LoaderClass = null;
    
    // Preload the GLB file immediately
    function preloadModel() {
        // Create a link preload hint for faster loading
        const link = document.createElement('link');
        link.rel = 'preload';
        link.as = 'fetch';
        link.href = '/static/butterflies.glb';
        link.crossOrigin = 'anonymous';
        document.head.appendChild(link);
    }
    
    // Wait for Three.js and GLTFLoader to be available - check more frequently
    let threeJsWaitAttempts = 0;
    const maxWaitAttempts = 200; // 10 seconds max (200 * 50ms)
    
    function waitForThree() {
        threeJsWaitAttempts++;
        
        if (typeof THREE === 'undefined') {
            if (threeJsWaitAttempts >= maxWaitAttempts) {
                console.error('3D Background: THREE.js failed to load after', maxWaitAttempts * 50, 'ms');
                return;
            }
            setTimeout(waitForThree, 50); // Check more frequently
            return;
        }
        
        console.log('3D Background: THREE.js loaded, checking for GLTFLoader...');
        
        // Check if GLTFLoader is available (might be in global scope or THREE namespace)
        if (typeof THREE.GLTFLoader !== 'undefined') {
            LoaderClass = THREE.GLTFLoader;
            loaderReady = true;
            console.log('3D Background: GLTFLoader found in THREE namespace');
        } else if (typeof GLTFLoader !== 'undefined') {
            LoaderClass = GLTFLoader;
            loaderReady = true;
            console.log('3D Background: GLTFLoader found in global scope');
        } else {
            if (threeJsWaitAttempts >= maxWaitAttempts) {
                console.error('3D Background: GLTFLoader failed to load after', maxWaitAttempts * 50, 'ms');
                console.error('3D Background: THREE.GLTFLoader:', typeof THREE.GLTFLoader, 'GLTFLoader:', typeof GLTFLoader);
                return;
            }
            setTimeout(waitForThree, 50); // Check more frequently
            return;
        }
        
        // CRITICAL: Start loading model immediately on startup, regardless of theme
        // This ensures the model is cached by the browser for instant loading on all pages
        if (loaderReady && !modelLoaded) {
            console.log('3D Background: Starting model preload on startup for all pages...');
            loadModel();
        }
        
        // Initialize theme checking immediately
        checkTheme();
        
        // Watch for theme changes (only if body exists)
        if (document.body) {
            const observer = new MutationObserver(checkTheme);
            observer.observe(document.body, {
                attributes: true,
                attributeFilter: ['class']
            });
            console.log('3D Background: Set up theme change observer on body');
        } else {
            // Wait for body to be available
            const bodyObserver = new MutationObserver(function() {
                if (document.body) {
                    bodyObserver.disconnect();
        const observer = new MutationObserver(checkTheme);
        observer.observe(document.body, {
            attributes: true,
            attributeFilter: ['class']
        });
                    console.log('3D Background: Set up theme change observer on body (delayed)');
                }
            });
            bodyObserver.observe(document.documentElement, { childList: true });
        }
    }
    
    // Load the model as soon as possible (before theme check)
    // This function loads the model immediately on startup to cache it for all pages
    function loadModel() {
        if (modelLoaded || !loaderReady || !LoaderClass) return;
        
        // Prevent multiple simultaneous loads
        if (window._modelLoadingInProgress) {
            console.log('3D Background: Model load already in progress, skipping...');
            return;
        }
        window._modelLoadingInProgress = true;
        
        console.log('3D Background: Preloading model for all pages...');
        const loader = new LoaderClass();
        const modelUrl = '/static/butterflies.glb';

        function onGltfLoaded(gltf) {
            console.log('3D Background: Model loaded successfully and cached');
            window._modelLoadingInProgress = false;
            model = gltf.scene;

            if (!model) {
                console.warn('3D Background: Model scene is empty');
                return;
            }

            const box = new THREE.Box3().setFromObject(model);
            const center = box.getCenter(new THREE.Vector3());
            const size = box.getSize(new THREE.Vector3());
            const maxDim = Math.max(size.x, size.y, size.z);
            const scale = maxDim > 0 ? 25 / maxDim : 1;
            model.scale.multiplyScalar(scale);
            model.position.sub(center.multiplyScalar(scale));
            model.position.y = -0.5;
            model.rotation.set(0, 0, 0);
            model.traverse(function (child) {
                if (child.isMesh || child.isGroup || child.isObject3D) {
                    child.rotation.set(0, 0, 0);
                }
            });
            modelLoaded = true;

            if (isDefaultTheme && scene && renderer && camera) {
                if (!scene.children.includes(model)) {
                    scene.add(model);
                }
                renderer.render(scene, camera);
                if (!animationId) {
                    animate();
                }
            }
        }

        fetch(modelUrl)
            .then(function (res) {
                if (!res.ok) {
                    throw new Error('HTTP ' + res.status);
                }
                return res.arrayBuffer();
            })
            .then(function (buffer) {
                if (!buffer || buffer.byteLength < 12) {
                    throw new Error('Model file too small or truncated');
                }
                const magic = new TextDecoder().decode(new Uint8Array(buffer, 0, 4));
                if (magic !== 'glTF') {
                    throw new Error('Response is not a glTF file (server may be down)');
                }
                loader.parse(
                    buffer,
                    modelUrl,
                    onGltfLoaded,
                    function (err) {
                        window._modelLoadingInProgress = false;
                        console.warn('3D Background: Could not parse model:', err);
                    }
                );
            })
            .catch(function (err) {
                window._modelLoadingInProgress = false;
                console.warn('3D Background: Model skipped:', err.message || err);
            });
    }
    
    // Check if default theme is active
    function checkTheme() {
        const body = document.body;
        const html = document.documentElement;
        const wasDefault = isDefaultTheme;
        
        // PRIMARY: Check localStorage first - most reliable source
        const savedTheme = localStorage.getItem('pos-theme') || 'default';
        
        // Default theme is when savedTheme is 'default' or empty/null
        isDefaultTheme = (savedTheme === 'default' || !savedTheme);
        
        // SECONDARY: Also check DOM classes as fallback (in case localStorage is out of sync)
        if (!isDefaultTheme) {
            // If localStorage says not default, double-check DOM classes
            const themeClasses = ['theme-default', 'theme-light', 'theme-classic'];
            let hasThemeClass = false;
            if (body) {
                hasThemeClass = themeClasses.some(cls => body.classList.contains(cls));
            }
            if (!hasThemeClass && html) {
                hasThemeClass = themeClasses.some(cls => html.classList.contains(cls));
            }
            // If no theme class found but localStorage says not default, trust DOM
            // (This handles edge case where localStorage is stale but DOM is correct)
            if (!hasThemeClass) {
                isDefaultTheme = true;
            }
        } else {
            // If localStorage says default, verify DOM doesn't have conflicting theme class
            const themeClasses = ['theme-light', 'theme-classic'];
            let hasThemeClass = false;
            if (body) {
                hasThemeClass = themeClasses.some(cls => body.classList.contains(cls));
            }
            if (!hasThemeClass && html) {
                hasThemeClass = themeClasses.some(cls => html.classList.contains(cls));
            }
            // If DOM has a theme class but localStorage says default, trust localStorage
            // (But this shouldn't happen in normal operation)
            if (hasThemeClass) {
                console.warn('3D Background: Theme mismatch - localStorage says default but DOM has theme class');
            }
        }
        
        console.log('3D Background: Theme check - savedTheme:', savedTheme, 'isDefaultTheme:', isDefaultTheme, 'wasDefault:', wasDefault);
        
        if (isDefaultTheme && !wasDefault) {
            // Theme changed to default - initialize 3D background immediately
            console.log('3D Background: Switching to default theme, initializing...');
            init3DBackground();
        } else if (!isDefaultTheme && wasDefault) {
            // Theme changed away from default - cleanup
            console.log('3D Background: Switching away from default theme, cleaning up...');
            cleanup3DBackground();
        } else if (isDefaultTheme) {
            // Default theme - ensure 3D background is initialized
            const canvas = document.getElementById('bg3d-canvas');
            if (canvas) {
                // Always initialize if default theme and canvas exists
                if (typeof THREE !== 'undefined') {
                    if (canvas.style.display === 'none' || !scene) {
                        console.log('3D Background: Default theme active, initializing/reinitializing...');
                init3DBackground();
                    } else if (canvas.style.display !== 'block') {
                        // Make sure canvas is visible
                        canvas.style.display = 'block';
                        console.log('3D Background: Default theme active, making canvas visible...');
                    }
                } else {
                    // THREE.js not loaded yet, wait for it
                    console.log('3D Background: Default theme active but THREE.js not ready, will initialize when ready...');
                    if (!window._threeJsWaitStarted) {
                        window._threeJsWaitStarted = true;
                        waitForThree();
                    }
                }
            } else {
                console.warn('3D Background: Default theme active but canvas element not found');
            }
        }
    }
    
    // Initialize 3D background
    function init3DBackground() {
        // Check if 3D background is disabled (e.g., on admin page)
        if (window._disable3DBackground === true) {
            console.log('3D Background: Disabled by _disable3DBackground flag');
            return;
        }
        
        const canvas = document.getElementById('bg3d-canvas');
        if (!canvas) {
            console.error('3D Background: Canvas element not found');
            return;
        }
        
        console.log('3D Background: Initializing...');
        
        // Show canvas and ensure it's visible - use setProperty with !important
        canvas.style.setProperty('display', 'block', 'important');
        canvas.style.setProperty('visibility', 'visible', 'important');
        canvas.style.setProperty('opacity', '1', 'important');
        canvas.style.setProperty('z-index', '-1', 'important');
        canvas.style.setProperty('background', 'transparent', 'important');
        
        // Force a reflow to ensure styles are applied
        void canvas.offsetWidth;
        
        // Verify canvas is actually visible
        const canvasRect = canvas.getBoundingClientRect();
        const computedStyle = window.getComputedStyle(canvas);
        const isVisible = computedStyle.display !== 'none' && 
                         computedStyle.visibility !== 'hidden' && 
                         parseFloat(computedStyle.opacity) > 0 &&
                         canvasRect.width > 0 && 
                         canvasRect.height > 0;
        
        console.log('3D Background: Canvas initialized -', {
            display: computedStyle.display,
            visibility: computedStyle.visibility,
            opacity: computedStyle.opacity,
            zIndex: computedStyle.zIndex,
            width: canvasRect.width,
            height: canvasRect.height,
            visible: isVisible,
            canvasVisible: canvasRect.width > 0 && canvasRect.height > 0
        });
        
        if (!isVisible) {
            console.warn('3D Background: Canvas is not visible! Check CSS rules.');
        }
        
        // Check if Three.js is available
        if (typeof THREE === 'undefined') {
            console.error('3D Background: Three.js not loaded');
            canvas.style.display = 'none';
            return;
        }
        
        // Check if GLTFLoader is available
        let LoaderClass = null;
        if (typeof THREE.GLTFLoader !== 'undefined') {
            LoaderClass = THREE.GLTFLoader;
        } else if (typeof GLTFLoader !== 'undefined') {
            LoaderClass = GLTFLoader;
        } else {
            console.error('3D Background: GLTFLoader not found. THREE.GLTFLoader:', typeof THREE.GLTFLoader, 'GLTFLoader:', typeof GLTFLoader);
            canvas.style.display = 'none';
            return;
        }
        
        console.log('3D Background: Three.js and GLTFLoader loaded');
        
        // Scene setup
        scene = new THREE.Scene();
        
        // Camera setup - perspective camera for 3D effect
        camera = new THREE.PerspectiveCamera(
            75, // FOV
            window.innerWidth / window.innerHeight,
            0.1,
            1000
        );
        // Position camera for top-down view at 45-degree angle of depression
        // Camera positioned above and looking down at 45 degrees - zoomed out more
        const cameraDistance = 13; // Zoomed out more for better view (was 10)
        const angleRad = Math.PI / 4; // 45 degrees in radians
        // Position camera: equal height and forward distance for 45-degree angle
        const height = cameraDistance * Math.sin(angleRad); // Height above center
        const forward = cameraDistance * Math.cos(angleRad); // Distance forward
        camera.position.set(0, height, forward); // Camera above and in front
        // Make camera look at the center (0, 0, 0) - this creates the 45-degree depression angle
        camera.lookAt(0, 0, 0);
        
        // Renderer setup
        renderer = new THREE.WebGLRenderer({
            canvas: canvas,
            alpha: true, // Transparent background
            antialias: true
        });
        renderer.setSize(window.innerWidth, window.innerHeight);
        renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2)); // Limit pixel ratio for performance
        renderer.setClearColor(0x000000, 0); // Transparent
        
        // Lighting for better visibility
        const ambientLight = new THREE.AmbientLight(0xffffff, 1.0);
        scene.add(ambientLight);
        
        const directionalLight1 = new THREE.DirectionalLight(0xffffff, 0.8);
        directionalLight1.position.set(5, 5, 5);
        scene.add(directionalLight1);
        
        const directionalLight2 = new THREE.DirectionalLight(0xffffff, 0.6);
        directionalLight2.position.set(-5, -5, -5);
        scene.add(directionalLight2);
        
        // Add a point light for extra visibility
        const pointLight = new THREE.PointLight(0xffffff, 0.5);
        pointLight.position.set(0, 0, 5);
        scene.add(pointLight);
        
        // Render an empty scene once to ensure renderer is working
        renderer.render(scene, camera);
        console.log('3D Background: Initial render complete, scene has', scene.children.length, 'children');
        
        // If model is already loaded, add it to scene immediately
        if (modelLoaded && model) {
            console.log('3D Background: Model already loaded, adding to scene immediately');
            // Check if model is already in scene to avoid duplicates
            if (!scene.children.includes(model)) {
            scene.add(model);
                console.log('3D Background: Model added to scene');
            }
            renderer.render(scene, camera);
            // Start animation loop if not already running
            if (!animationId) {
                console.log('3D Background: Starting animation loop...');
            animate();
            }
        } else if (loaderReady && LoaderClass) {
            // Model not loaded yet, start loading it now
            if (!modelLoaded && !window._modelLoadingInProgress) {
                console.log('3D Background: Starting model load from init3DBackground...');
                loadModel();
                // Set up a check to add model when it finishes loading
                const checkModelLoaded = setInterval(function() {
                    if (modelLoaded && model && scene && !scene.children.includes(model)) {
                        clearInterval(checkModelLoaded);
                        console.log('3D Background: Model loaded during init, adding to scene...');
                        scene.add(model);
                        renderer.render(scene, camera);
                        // Start animation loop if not already running
                        if (!animationId) {
                            console.log('3D Background: Starting animation loop after model load...');
                            animate();
                        }
                    }
                }, 100);
                // Timeout after 30 seconds
                setTimeout(() => clearInterval(checkModelLoaded), 30000);
            } else if (window._modelLoadingInProgress) {
                // Model is currently loading, wait for it
                console.log('3D Background: Model is loading, waiting for it to finish...');
                const checkModelLoaded = setInterval(function() {
                    if (modelLoaded && model && scene && !scene.children.includes(model)) {
                        clearInterval(checkModelLoaded);
                        console.log('3D Background: Model finished loading, adding to scene...');
                        scene.add(model);
                        renderer.render(scene, camera);
                        // Start animation loop if not already running
                        if (!animationId) {
                            console.log('3D Background: Starting animation loop after model load...');
                            animate();
                        }
                    }
                }, 100);
                // Timeout after 30 seconds
                setTimeout(() => clearInterval(checkModelLoaded), 30000);
            }
        } else {
            // Wait for loader to be ready, then load
            console.log('3D Background: Waiting for loader to be ready...');
            const checkLoader = setInterval(function() {
                if (loaderReady && LoaderClass && !modelLoaded && !window._modelLoadingInProgress) {
                    clearInterval(checkLoader);
                    console.log('3D Background: Loader ready, starting model load...');
                    loadModel();
                    // Set up check to add model when it loads
                    const checkModelLoaded = setInterval(function() {
                        if (modelLoaded && model && scene && !scene.children.includes(model)) {
                            clearInterval(checkModelLoaded);
                            console.log('3D Background: Model loaded, adding to scene...');
                            scene.add(model);
                            renderer.render(scene, camera);
                            // Start animation loop if not already running
                            if (!animationId) {
                                console.log('3D Background: Starting animation loop after model load...');
                                animate();
                            }
                        }
                    }, 100);
                    // Timeout after 30 seconds
                    setTimeout(() => clearInterval(checkModelLoaded), 30000);
                } else if (modelLoaded && model && scene && !scene.children.includes(model)) {
                    clearInterval(checkLoader);
                    console.log('3D Background: Model loaded while waiting for loader, adding to scene...');
                    scene.add(model);
                    renderer.render(scene, camera);
                    // Start animation loop if not already running
                    if (!animationId) {
                        console.log('3D Background: Starting animation loop after model load...');
                    animate();
                    }
                }
            }, 100);
            // Timeout after 30 seconds
            setTimeout(() => clearInterval(checkLoader), 30000);
        }
        
        // Handle window resize
        window.addEventListener('resize', onWindowResize);
        
        // Always start animation loop, even if model isn't loaded yet
        // This ensures the renderer is active and will render when model loads
        if (!animationId && isDefaultTheme) {
            console.log('3D Background: Starting animation loop immediately (model may load later)...');
            animate();
        }
        
        // Final visibility check after a short delay
        setTimeout(() => {
            const finalCheck = window.getComputedStyle(canvas);
            const finalRect = canvas.getBoundingClientRect();
            console.log('3D Background: Final visibility check after init -', {
                display: finalCheck.display,
                visibility: finalCheck.visibility,
                opacity: finalCheck.opacity,
                zIndex: finalCheck.zIndex,
                dimensions: finalRect.width + 'x' + finalRect.height,
                visible: finalCheck.display !== 'none' && finalRect.width > 0 && finalRect.height > 0
            });
            
            if (finalCheck.display === 'none') {
                console.error('3D Background: Canvas is still hidden! CSS or JS issue.');
            }
        }, 500);
        
        console.log('3D Background: Initialization complete, scene ready, animation:', animationId ? 'running' : 'not started');
    }
    
    // Animation loop with smooth timing
    let lastTime = null;
    function animate(currentTime) {
        if (!isDefaultTheme || !scene || !camera || !renderer) {
            console.log('3D Background: Animation stopped - isDefaultTheme:', isDefaultTheme, 'scene:', !!scene, 'camera:', !!camera, 'renderer:', !!renderer);
            lastTime = null;
            if (animationId) {
                cancelAnimationFrame(animationId);
                animationId = null;
            }
            return;
        }
        
        animationId = requestAnimationFrame(animate);
        
        // Calculate delta time for smooth animation independent of frame rate
        const now = currentTime || performance.now();
        const deltaTime = lastTime !== null ? (now - lastTime) / 1000 : 0.016; // Default to ~60fps if first frame
        lastTime = now;
        
        // Find model in scene if it exists, or use the global model reference
        let modelToAnimate = model;
        if (!modelToAnimate && scene && scene.children.length > 0) {
            // Try to find the model in the scene children (skip lights and camera)
            for (let i = 0; i < scene.children.length; i++) {
                const child = scene.children[i];
                // Skip lights and camera
                if (child && 
                    child.type !== 'AmbientLight' && 
                    child.type !== 'DirectionalLight' && 
                    child.type !== 'PointLight' &&
                    (child.type === 'Group' || child.type === 'Object3D') && 
                    child.children && child.children.length > 0) {
                    modelToAnimate = child;
                    break;
                }
            }
        }
        
        // Rotate model - only rotate parent, children will follow automatically
        if (modelToAnimate && modelToAnimate.rotation !== undefined) {
            // Smooth rotation using delta time for consistent speed regardless of FPS
            // Increased speed: 2.0 degrees per second (was 0.5)
            const rotationSpeed = 2.0; // degrees per second
            modelToAnimate.rotation.y += (rotationSpeed * Math.PI / 180) * deltaTime;
            
            // Smooth floating motion using delta time
            // Increased speed: 1.5 cycles per second (was 0.5)
            const baseY = -0.5; // Base Y position
            const floatSpeed = 1.5; // cycles per second
            const floatAmplitude = 0.3; // amplitude of float
            const time = now * 0.001 * floatSpeed;
            modelToAnimate.position.y = baseY + Math.sin(time) * floatAmplitude;
        }
        
        // Always render the scene, even if model isn't loaded yet
        renderer.render(scene, camera);
        
        // Log render info for debugging
        if (scene.children.length > 0) {
            console.log('3D Background: Rendered scene with', scene.children.length, 'objects');
        }
    }
    
    // Handle window resize
    function onWindowResize() {
        if (!camera || !renderer) return;
        
        camera.aspect = window.innerWidth / window.innerHeight;
        camera.updateProjectionMatrix();
        renderer.setSize(window.innerWidth, window.innerHeight);
    }
    
    // Cleanup 3D background
    function cleanup3DBackground() {
        const canvas = document.getElementById('bg3d-canvas');
        if (canvas) {
            canvas.style.display = 'none';
        }
        
        if (animationId) {
            cancelAnimationFrame(animationId);
            animationId = null;
        }
        
        if (renderer) {
            renderer.dispose();
            renderer = null;
        }
        
        scene = null;
        camera = null;
        model = null;
        
        window.removeEventListener('resize', onWindowResize);
    }
    
    // Start preloading immediately (before DOM ready)
    preloadModel();
    
    // Immediate theme check based on localStorage (doesn't require DOM)
    function immediateThemeCheck() {
        const savedTheme = localStorage.getItem('pos-theme') || 'default';
        isDefaultTheme = (savedTheme === 'default' || !savedTheme);
        console.log('3D Background: Immediate check - savedTheme:', savedTheme, 'isDefaultTheme:', isDefaultTheme);
    }
    
    // Run immediate check right away (before DOM ready)
    immediateThemeCheck();
    
    // Initialize - wait for Three.js to load
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function() {
            console.log('3D Background: DOM loaded, initializing...');
            waitForThree();
            // Immediate theme check when body is available
            setTimeout(() => {
                checkTheme();
                // Force check again after delays to catch any late theme applications
                setTimeout(checkTheme, 100);
                setTimeout(checkTheme, 500);
                setTimeout(checkTheme, 1000);
            }, 50);
        });
    } else {
        console.log('3D Background: DOM ready, initializing...');
        waitForThree();
        // Immediate theme check when body is available
        setTimeout(() => {
            checkTheme();
            // Force check again after delays to catch any late theme applications
            setTimeout(checkTheme, 100);
            setTimeout(checkTheme, 500);
            setTimeout(checkTheme, 1000);
        }, 50);
    }
})();

