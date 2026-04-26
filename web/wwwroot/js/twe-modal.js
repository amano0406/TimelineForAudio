(() => {
    const getModalApi = () => window.twe?.Modal || null;

    const getOrCreate = (element) => {
        if (!element) {
            return null;
        }

        const api = getModalApi();
        if (!api) {
            return null;
        }

        return api.getOrCreateInstance(element);
    };

    const show = (element, relatedTarget) => {
        if (!element) {
            return;
        }

        const modal = getOrCreate(element);
        if (!modal) {
            element.classList.remove("hidden");
            element.removeAttribute("aria-hidden");
            return;
        }

        modal.show(relatedTarget);
    };

    const hide = (element) => {
        if (!element) {
            return;
        }

        const modal = getOrCreate(element);
        if (!modal) {
            element.classList.add("hidden");
            element.setAttribute("aria-hidden", "true");
            return;
        }

        modal.hide();
    };

    const on = (element, eventName, handler) => {
        if (!element || typeof handler !== "function") {
            return;
        }

        element.addEventListener(eventName, handler);
    };

    window.timelineForAudioModal = {
        getOrCreate,
        show,
        hide,
        onShown(element, handler) {
            on(element, "shown.twe.modal", handler);
        },
        onHidden(element, handler) {
            on(element, "hidden.twe.modal", handler);
        },
    };
})();
