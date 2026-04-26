(() => {
    const getTooltipClass = () => window.twe?.Tooltip ?? null;

    const getOrCreate = (element) => {
        if (!(element instanceof Element)) {
            return null;
        }

        const Tooltip = getTooltipClass();
        if (!Tooltip?.getOrCreateInstance) {
            return null;
        }

        return Tooltip.getOrCreateInstance(element, {
            container: "body",
            placement: element.getAttribute("data-twe-placement") || "top",
            trigger: "hover focus",
            title: element.getAttribute("title") || element.getAttribute("aria-label") || "",
        });
    };

    const apply = (root = document) => {
        if (!root) {
            return;
        }

        root.querySelectorAll("[data-twe-tooltip-ref]").forEach((element) => {
            getOrCreate(element);
        });
    };

    document.addEventListener("DOMContentLoaded", () => {
        apply(document);
    });

    window.timelineForAudioTooltip = {
        apply,
        getOrCreate,
    };
})();
