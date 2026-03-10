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
