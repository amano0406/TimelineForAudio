(() => {
    const applyConfig = (selector, color, root) => {
        root.querySelectorAll(selector).forEach((element) => {
            if (!(element instanceof HTMLElement)) {
                return;
            }

            if (
                element.classList.contains("btn-disabled") ||
                element.classList.contains("nav-link-disabled") ||
                element.hasAttribute("disabled") ||
                element.getAttribute("aria-disabled") === "true"
            ) {
                return;
            }

            if (!element.hasAttribute("data-twe-ripple-init")) {
                element.setAttribute("data-twe-ripple-init", "");
            }

            if (color && !element.hasAttribute("data-twe-ripple-color")) {
                element.setAttribute("data-twe-ripple-color", color);
            }
        });
    };

    const apply = (root = document) => {
        if (!root || !window.twe?.Ripple) {
            return;
        }

        applyConfig(".btn-primary", "light", root);
        applyConfig(".btn-secondary, .btn-table, .selection-remove-button, .nav-link", "primary", root);
        applyConfig(".btn-table-success", "success", root);
        applyConfig(".btn-table-danger", "danger", root);
        applyConfig(".twe-choice-card, .setup-choice-button, .settings-row-summary, .soft-callout-summary", "primary", root);
    };

    document.addEventListener("DOMContentLoaded", () => {
        apply(document);
    });

    window.timelineForAudioRipple = {
        apply,
    };
})();
