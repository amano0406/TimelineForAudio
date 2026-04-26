(() => {
    const resolveToggle = (candidate) => {
        if (candidate instanceof Element) {
            return candidate;
        }

        if (typeof candidate === "string" && candidate.length > 0) {
            return document.querySelector(candidate);
        }

        return null;
    };

    const fallbackHide = (toggle) => {
        if (!(toggle instanceof Element)) {
            return;
        }

        toggle.removeAttribute("data-twe-dropdown-show");
        toggle.setAttribute("aria-expanded", "false");

        const menu = toggle.nextElementSibling;
        if (menu instanceof Element && menu.hasAttribute("data-twe-dropdown-menu-ref")) {
            menu.removeAttribute("data-twe-dropdown-show");
        }
    };

    const getDropdownClass = () => window.twe?.Dropdown ?? null;

    const getOrCreate = (candidate) => {
        const toggle = resolveToggle(candidate);
        if (!(toggle instanceof Element)) {
            return null;
        }

        const Dropdown = getDropdownClass();
        if (!Dropdown?.getOrCreateInstance) {
            return {
                hide: () => fallbackHide(toggle)
            };
        }

        return Dropdown.getOrCreateInstance(toggle);
    };

    const hide = (candidate) => {
        const instance = getOrCreate(candidate);
        if (instance?.hide) {
            instance.hide();
            return;
        }

        fallbackHide(resolveToggle(candidate));
    };

    document.addEventListener("DOMContentLoaded", () => {
        document.querySelectorAll("[data-twe-dropdown-toggle-ref]").forEach((toggle) => {
            getOrCreate(toggle);
        });
    });

    window.timelineForAudioDropdown = {
        getOrCreate,
        hide
    };
})();
