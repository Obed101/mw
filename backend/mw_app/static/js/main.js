// Market Window global UI behavior
document.addEventListener("DOMContentLoaded", () => {
    const overlay = document.getElementById("global-loading-overlay");
    const overlayText = document.getElementById("global-loading-text");
    const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute("content");
    const popoverSelector = '[data-bs-toggle="popover"]';

    if (window.htmx && csrfToken) {
        document.body.addEventListener("htmx:configRequest", (event) => {
            event.detail.headers["X-CSRFToken"] = csrfToken;
        });
    }

    function initPopovers(root = document) {
        if (!window.bootstrap || !window.bootstrap.Popover) return;

        const nodes = [];
        if (root.matches && root.matches(popoverSelector)) {
            nodes.push(root);
        }
        if (root.querySelectorAll) {
            nodes.push(...root.querySelectorAll(popoverSelector));
        }

        nodes.forEach((node) => {
            if (!window.bootstrap.Popover.getInstance(node)) {
                new window.bootstrap.Popover(node);
            }
        });
    }

    function showOverlay(message) {
        if (!overlay) return;
        if (overlayText && message) {
            overlayText.textContent = message;
        }
        overlay.classList.add("is-visible");
        overlay.setAttribute("aria-hidden", "false");
    }

    const bottomNav = document.querySelector(".bottom-nav");
    const bottomNavTargets = bottomNav
        ? Array.from(bottomNav.querySelectorAll(".bottom-nav-item"))
            .map((item) => {
                if (!(item instanceof Element)) return null;
                if (item.matches("button.bottom-nav-btn")) {
                    return { element: item, path: "/profile" };
                }

                const href = item.getAttribute("href");
                if (!href) return null;

                try {
                    return { element: item, path: new URL(href, window.location.origin).pathname };
                } catch (error) {
                    return null;
                }
            })
            .filter(Boolean)
        : [];

    let swipeState = null;
    let swipeNavigationLocked = false;

    function normalizePath(pathname) {
        const cleaned = String(pathname || "").replace(/\/+$/, "");
        return cleaned || "/";
    }

    function isPathMatch(currentPath, targetPath) {
        const normalizedCurrent = normalizePath(currentPath);
        const normalizedTarget = normalizePath(targetPath);
        return normalizedCurrent === normalizedTarget || normalizedCurrent.startsWith(`${normalizedTarget}/`);
    }

    function hasBlockingOverlay() {
        return Boolean(document.querySelector(".modal.show, .offcanvas.show, .dropdown-menu.show, .global-loading-overlay.is-visible"));
    }

    function isHorizontalScrollable(element) {
        if (!(element instanceof Element)) return false;
        const style = window.getComputedStyle(element);
        if (!/(auto|scroll|overlay)/.test(style.overflowX)) return false;
        return element.scrollWidth > element.clientWidth + 8;
    }

    function shouldIgnoreSwipe(target) {
        if (hasBlockingOverlay()) return true;
        if (!(target instanceof Element)) return true;

        if (target.closest(
            ".bottom-nav, .modal, .offcanvas, .dropdown-menu, .pswp, .carousel, .swiper, .leaflet-container, .gm-style, .mapboxgl-map, [data-bs-touch=\"true\"], [data-no-swipe=\"true\"], [data-swipe-ignore=\"true\"]"
        )) {
            return true;
        }

        if (target.closest("input, textarea, select, option, button, [contenteditable=\"true\"], [contenteditable=\"\"], [role=\"button\"]")) {
            return true;
        }

        let node = target;
        while (node && node !== document.body) {
            if (node instanceof Element && isHorizontalScrollable(node)) {
                return true;
            }
            node = node.parentElement;
        }

        return false;
    }

    function getCurrentNavIndex() {
        return bottomNavTargets.findIndex((entry) => isPathMatch(window.location.pathname, entry.path));
    }

    function startSwipeNavigation(clientX, clientY, target) {
        if (swipeNavigationLocked || shouldIgnoreSwipe(target)) return;

        swipeState = {
            startX: clientX,
            startY: clientY,
            lastX: clientX,
            lastY: clientY,
            startTime: performance.now(),
            locked: false,
            cancelled: false,
        };
    }

    function updateSwipeNavigation(clientX, clientY, event) {
        if (!swipeState || swipeState.cancelled) return;

        swipeState.lastX = clientX;
        swipeState.lastY = clientY;

        const deltaX = clientX - swipeState.startX;
        const deltaY = clientY - swipeState.startY;
        const absX = Math.abs(deltaX);
        const absY = Math.abs(deltaY);

        if (!swipeState.locked) {
            if (absX < 12 && absY < 12) return;

            if (absY > absX * 1.05) {
                swipeState.cancelled = true;
                return;
            }

            if (absX > absY * 1.2) {
                swipeState.locked = true;
            }
        }

        if (swipeState.locked && event && event.cancelable) {
            event.preventDefault();
        }
    }

    function finishSwipeNavigation(clientX, clientY) {
        if (!swipeState) return;

        const state = swipeState;
        swipeState = null;

        if (state.cancelled || swipeNavigationLocked) return;

        const deltaX = clientX - state.startX;
        const deltaY = clientY - state.startY;
        const absX = Math.abs(deltaX);
        const absY = Math.abs(deltaY);
        const elapsed = Math.max(performance.now() - state.startTime, 1);
        const velocityX = absX / elapsed;

        if (absX < 72) return;
        if (absX <= absY * 1.2) return;
        if (velocityX < 0.35 && absX < 110) return;

        const currentIndex = getCurrentNavIndex();
        if (currentIndex < 0) return;

        const direction = deltaX < 0 ? 1 : -1;
        const nextIndex = currentIndex + direction;
        if (nextIndex < 0 || nextIndex >= bottomNavTargets.length) return;

        const nextTarget = bottomNavTargets[nextIndex];
        if (!nextTarget || !nextTarget.path) return;
        if (isPathMatch(window.location.pathname, nextTarget.path)) return;

        swipeNavigationLocked = true;
        document.body.classList.add("mw-page-transitioning");
        window.requestAnimationFrame(() => {
            window.setTimeout(() => {
                window.location.assign(nextTarget.path);
            }, 220);
        });
    }

    function cancelSwipeNavigation() {
        swipeState = null;
    }

    if (window.PointerEvent) {
        document.addEventListener("pointerdown", (event) => {
            if (event.pointerType !== "touch" && event.pointerType !== "pen") return;
            if (event.isPrimary === false) return;
            startSwipeNavigation(event.clientX, event.clientY, event.target);
        }, { passive: true });

        document.addEventListener("pointermove", (event) => {
            if (event.pointerType !== "touch" && event.pointerType !== "pen") return;
            updateSwipeNavigation(event.clientX, event.clientY, event);
        }, { passive: false });

        document.addEventListener("pointerup", (event) => {
            if (event.pointerType !== "touch" && event.pointerType !== "pen") return;
            finishSwipeNavigation(event.clientX, event.clientY);
        }, { passive: true });

        document.addEventListener("pointercancel", cancelSwipeNavigation, { passive: true });
    } else {
        let touchIdentifier = null;

        document.addEventListener("touchstart", (event) => {
            if (event.touches.length !== 1) {
                cancelSwipeNavigation();
                return;
            }
            const touch = event.touches[0];
            touchIdentifier = touch.identifier;
            startSwipeNavigation(touch.clientX, touch.clientY, event.target);
        }, { passive: true });

        document.addEventListener("touchmove", (event) => {
            const touch = Array.from(event.touches).find((item) => item.identifier === touchIdentifier);
            if (!touch) return;
            updateSwipeNavigation(touch.clientX, touch.clientY, event);
        }, { passive: false });

        document.addEventListener("touchend", (event) => {
            const touch = Array.from(event.changedTouches).find((item) => item.identifier === touchIdentifier);
            if (!touch) return;
            finishSwipeNavigation(touch.clientX, touch.clientY);
            touchIdentifier = null;
        }, { passive: true });

        document.addEventListener("touchcancel", () => {
            touchIdentifier = null;
            cancelSwipeNavigation();
        }, { passive: true });
    }

    function dismissToast(toast) {
        if (!toast || toast.classList.contains("is-leaving")) return;
        toast.classList.add("is-leaving");
        window.setTimeout(() => toast.remove(), 360);
    }

    const notificationDropdown = document.querySelector(".notification-dropdown");
    const notificationList = document.getElementById("notification-dropdown-list");
    const notificationCount = document.getElementById("notification-count");
    const markAllNotificationsReadButton = document.getElementById("notifications-read-all");

    function escapeHtml(value) {
        return String(value || "")
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }

    function iconForNotification(icon) {
        const icons = {
            order: "bag-check",
            shop: "shop",
            product: "box-seam",
            user: "person",
            support: "headset",
            system: "bell",
            location: "geo-alt",
        };
        return icons[icon] || "bell";
    }

    function updateNotificationBadge(count) {
        if (!notificationCount) return;
        const safeCount = Number(count || 0);
        notificationCount.textContent = safeCount > 99 ? "99+" : String(safeCount);
        notificationCount.style.display = safeCount > 0 ? "block" : "none";
    }

    function notificationReadUrl(id) {
        const template = notificationDropdown?.dataset.readUrlTemplate;
        return template ? template.replace(/\/0(\/|$)/, `/${id}$1`) : "";
    }

    function renderNotifications(notifications) {
        if (!notificationList) return;

        if (!notifications || notifications.length === 0) {
            notificationList.innerHTML = `
                <div class="p-4 text-center text-muted">
                    <i class="bi bi-bell-slash d-block fs-4 mb-2"></i>
                    <div class="small">No notifications yet</div>
                </div>
            `;
            return;
        }

        notificationList.innerHTML = notifications.map((notification) => {
            const icon = escapeHtml(notification.icon || "system");
            const title = escapeHtml(notification.title);
            const message = escapeHtml(notification.message);
            const time = escapeHtml(notification.created_at_label || "");
            const unreadClass = notification.is_read ? "" : " unread";
            const actionUrl = escapeHtml(notification.action_url || "");

            return `
                <button type="button"
                        class="notification-item text-start border-0 bg-transparent w-100${unreadClass}"
                        data-notification-id="${notification.id}"
                        data-action-url="${actionUrl}">
                    <span class="notification-icon ${icon}${unreadClass}">
                        <i class="bi bi-${iconForNotification(icon)}"></i>
                    </span>
                    <span class="notification-content">
                        <span class="notification-title d-block">${title}</span>
                        <span class="notification-message d-block">${message}</span>
                        <span class="notification-time d-block mt-1">${time}</span>
                    </span>
                </button>
            `;
        }).join("");
    }

    async function loadNotifications() {
        if (!notificationDropdown || !notificationList) return;
        const feedUrl = notificationDropdown.dataset.feedUrl;
        if (!feedUrl) return;

        try {
            const response = await fetch(feedUrl, {
                headers: { "Accept": "application/json" },
                credentials: "same-origin",
            });
            const data = await response.json();
            if (!response.ok || !data.success) {
                throw new Error(data.message || "Unable to load notifications");
            }
            updateNotificationBadge(data.unread_count);
            renderNotifications(data.notifications);
        } catch (error) {
            notificationList.innerHTML = '<div class="p-3 text-muted small">Notifications are unavailable right now.</div>';
        }
    }

    async function markNotificationRead(id) {
        const url = notificationReadUrl(id);
        if (!url) return;

        await fetch(url, {
            method: "POST",
            headers: {
                "Accept": "application/json",
                "X-CSRFToken": csrfToken || "",
            },
            credentials: "same-origin",
        });
    }

    if (notificationDropdown) {
        loadNotifications();

        document.addEventListener("shown.bs.dropdown", (event) => {
            if (event.target && event.target.querySelector && event.target.querySelector(".bi-bell")) {
                loadNotifications();
            }
        });

        notificationList?.addEventListener("click", async (event) => {
            const item = event.target.closest(".notification-item");
            if (!item) return;

            const notificationId = item.dataset.notificationId;
            const actionUrl = item.dataset.actionUrl;
            if (notificationId) {
                try {
                    await markNotificationRead(notificationId);
                } catch (error) {
                    // Still follow the notification target if the read update is interrupted.
                }
            }
            if (actionUrl) {
                window.location.href = actionUrl;
            } else {
                loadNotifications();
            }
        });

        markAllNotificationsReadButton?.addEventListener("click", async () => {
            const readAllUrl = notificationDropdown.dataset.readAllUrl;
            if (!readAllUrl) return;

            await fetch(readAllUrl, {
                method: "POST",
                headers: {
                    "Accept": "application/json",
                    "X-CSRFToken": csrfToken || "",
                },
                credentials: "same-origin",
            });
            loadNotifications();
        });
    }

    function initializeToasts(root = document) {
        root.querySelectorAll(".mw-toast").forEach((toast, index) => {
            if (toast.dataset.toastInitialized) return;
            toast.dataset.toastInitialized = "true";
            const delay = Number(toast.dataset.autodismiss || 15000) + (index * 120);
            window.setTimeout(() => dismissToast(toast), delay);

            const closeButton = toast.querySelector(".mw-toast-close");
            if (closeButton) {
                closeButton.addEventListener("click", () => dismissToast(toast));
            }
        });
    }

    initializeToasts();
    document.body.addEventListener("htmx:afterSwap", (event) => initializeToasts(event.target));

    document.querySelectorAll(".auth-google-btn").forEach((button) => {
        button.addEventListener("click", () => {
            showOverlay("Connecting to Google...");
        });
    });

    document.querySelectorAll("form.auth-form").forEach((form) => {
        form.addEventListener("submit", () => {
            const message = form.dataset.loadingMessage || "Signing you in...";
            showOverlay(message);
        });
    });

    // Central Event Tracking Pipeline
    window.trackEvent = function(eventType, entityType = null, entityId = null, payload = {}) {
        const body = {
            event_type: eventType,
            entity_type: entityType,
            entity_id: entityId,
            payload: payload
        };
        fetch('/api/analytics/track', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken || ''
            },
            body: JSON.stringify(body)
        }).catch(err => console.error('Tracking failed:', err));
    };

    // Global Event Delegation for Product-related UI actions
    document.body.addEventListener('click', (e) => {
        // Track Product Clicks (links to product detail pages)
        const productLink = e.target.closest('a[href*="/explore/products/"]');
        if (productLink) {
            const match = productLink.href.match(/\/explore\/products\/(\d+)/);
            if (match) {
                const productId = parseInt(match[1], 10);
                const payload = {};
                const parentSection = productLink.closest('[data-track-section]');
                if (parentSection) {
                    const source = parentSection.dataset.trackSection;
                    payload.source = source;
                    if (source === 'trending') {
                        window.trackEvent('trending_click', 'product', productId, payload);
                    } else if (source === 'recommendation') {
                        window.trackEvent('recommendation_click', 'product', productId, payload);
                    }
                }
                window.trackEvent('product_click', 'product', productId, payload);
            }
        }

        // Track General Elements with data-track-event attribute
        const trackable = e.target.closest('[data-track-event]');
        if (trackable) {
            const eventType = trackable.dataset.trackEvent;
            const entityType = trackable.dataset.entityType || null;
            const entityId = trackable.dataset.entityId ? parseInt(trackable.dataset.entityId, 10) : null;
            let payload = {};
            try {
                if (trackable.dataset.payload) {
                    payload = JSON.parse(trackable.dataset.payload);
                }
            } catch (err) {}
            window.trackEvent(eventType, entityType, entityId, payload);
        }
    });

    // Stay duration detection (long_product_view after 15s)
    const productDetailMatch = window.location.pathname.match(/\/explore\/products\/(\d+)/);
    if (productDetailMatch) {
        const productId = parseInt(productDetailMatch[1], 10);
        window.setTimeout(() => {
            window.trackEvent('long_product_view', 'product', productId, { duration_seconds: 15 });
        }, 15000);
    }

    // Scroll depth detection (deep_scroll depth >= 70%)
    let deepScrollTracked = false;
    window.addEventListener('scroll', () => {
        if (deepScrollTracked) return;
        const scrollTop = window.scrollY || window.pageYOffset || document.documentElement.scrollTop;
        const docHeight = document.documentElement.scrollHeight - document.documentElement.clientHeight;
        if (docHeight > 0) {
            const scrollPercent = (scrollTop / docHeight) * 100;
            if (scrollPercent >= 70) {
                deepScrollTracked = true;
                const match = window.location.pathname.match(/\/explore\/products\/(\d+)/);
                if (match) {
                    const productId = parseInt(match[1], 10);
                    window.trackEvent('deep_scroll', 'product', productId, { scroll_depth_percent: 70 });
                } else {
                    window.trackEvent('deep_scroll', null, null, { scroll_depth_percent: 70 });
                }
            }
        }
    }, { passive: true });

    // Geolocation Handling for Nearest Sorting
    window.mwSilentCaptureLocation = function() {
        if (!navigator.geolocation) return;
        navigator.geolocation.getCurrentPosition(
            function (pos) {
                sessionStorage.setItem('mw_loc_sent', '1');
                fetch('/api/buyer/location', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': csrfToken || ''
                    },
                    body: JSON.stringify({
                        latitude:  pos.coords.latitude,
                        longitude: pos.coords.longitude
                    })
                }).then(function () {
                    const productsContainer = document.getElementById('products-container');
                    if (productsContainer) htmx.trigger(productsContainer, 'load');
                    const shopsContainer = document.getElementById('shops-container');
                    if (shopsContainer) htmx.trigger(shopsContainer, 'load');
                }).catch(function (err) {
                    console.error('Location update failed', err);
                });
            },
            function () {
                // Silently ignore
            },
            { timeout: 8000, maximumAge: 300000 }
        );
    };

    window.mwRequestLocationPermission = function() {
        if (!navigator.geolocation) return;
        
        const btn = document.querySelector('#location-prompt-banner button');
        if (btn) {
            btn.disabled = true;
            btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1" role="status" aria-hidden="true"></span>Enabling...';
        }

        navigator.geolocation.getCurrentPosition(
            function (pos) {
                sessionStorage.setItem('mw_loc_sent', '1');
                const banner = document.getElementById('location-prompt-banner');
                if (banner) banner.classList.add('d-none');
                
                fetch('/api/buyer/location', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': csrfToken || ''
                    },
                    body: JSON.stringify({
                        latitude:  pos.coords.latitude,
                        longitude: pos.coords.longitude
                    })
                }).then(function () {
                    const productsContainer = document.getElementById('products-container');
                    if (productsContainer) htmx.trigger(productsContainer, 'load');
                    const shopsContainer = document.getElementById('shops-container');
                    if (shopsContainer) htmx.trigger(shopsContainer, 'load');
                }).catch(function (err) {
                    console.error('Location update failed', err);
                });
            },
            function (err) {
                if (btn) {
                    btn.disabled = false;
                    btn.innerHTML = 'Enable Location';
                }
                
                if (err.code === err.PERMISSION_DENIED) {
                    sessionStorage.setItem('mw_loc_sent', 'denied');
                    console.warn('Geolocation permission denied', err);
                    const bannerText = document.querySelector('#location-prompt-banner p');
                    if (bannerText) {
                        bannerText.textContent = "Location access was denied. Please enable location permissions in your browser settings to see nearest items.";
                    }
                    if (btn) btn.classList.add('d-none');
                } else {
                    console.warn('Geolocation acquisition error: ' + err.message, err);
                    const bannerText = document.querySelector('#location-prompt-banner p');
                    if (bannerText) {
                        bannerText.textContent = "Unable to retrieve your location (position unavailable or timeout). Please try again.";
                    }
                }
            },
            { timeout: 8000, maximumAge: 300000 }
        );
    };

    // Initialize Geolocation & Prompt Banner logic
    if (navigator.geolocation) {
        if (navigator.permissions && navigator.permissions.query) {
            navigator.permissions.query({ name: 'geolocation' }).then(function (result) {
                if (result.state === 'granted') {
                    window.mwSilentCaptureLocation();
                } else if (result.state === 'prompt') {
                    const banner = document.getElementById('location-prompt-banner');
                    if (banner) banner.classList.remove('d-none');
                }
            }).catch(function() {
                if (!sessionStorage.getItem('mw_loc_sent')) {
                    const banner = document.getElementById('location-prompt-banner');
                    if (banner) banner.classList.remove('d-none');
                }
            });
        } else {
            if (!sessionStorage.getItem('mw_loc_sent')) {
                const banner = document.getElementById('location-prompt-banner');
                if (banner) banner.classList.remove('d-none');
            }
        }
    }

    initPopovers();

    if (window.htmx) {
        document.body.addEventListener("htmx:afterSwap", (event) => {
            if (event.detail && event.detail.target) {
                initPopovers(event.detail.target);
            }
        });
    }
});
