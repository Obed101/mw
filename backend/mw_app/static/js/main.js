// Market Window global UI behavior
document.addEventListener("DOMContentLoaded", () => {
    const overlay = document.getElementById("global-loading-overlay");
    const overlayText = document.getElementById("global-loading-text");

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
});
