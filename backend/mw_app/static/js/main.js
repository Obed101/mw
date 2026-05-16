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

    document.querySelectorAll(".mw-toast").forEach((toast, index) => {
        const delay = Number(toast.dataset.autodismiss || 15000) + (index * 120);
        window.setTimeout(() => dismissToast(toast), delay);

        const closeButton = toast.querySelector(".mw-toast-close");
        if (closeButton) {
            closeButton.addEventListener("click", () => dismissToast(toast));
        }
    });

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

    initPopovers();

    if (window.htmx) {
        document.body.addEventListener("htmx:afterSwap", (event) => {
            if (event.detail && event.detail.target) {
                initPopovers(event.detail.target);
            }
        });
    }
});
