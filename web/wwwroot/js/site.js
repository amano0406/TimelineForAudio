(() => {
    const fallbackCopy = (text) => {
        const textarea = document.createElement("textarea");
        textarea.value = text;
        textarea.setAttribute("readonly", "readonly");
        textarea.style.position = "fixed";
        textarea.style.top = "-9999px";
        textarea.style.opacity = "0";
        document.body.appendChild(textarea);
        textarea.focus();
        textarea.select();

        let success = false;
        try {
            success = document.execCommand("copy");
        } catch {
            success = false;
        }

        document.body.removeChild(textarea);
        return success;
    };

    const copyText = async (text) => {
        if (navigator.clipboard && typeof navigator.clipboard.writeText === "function") {
            try {
                await navigator.clipboard.writeText(text);
                return true;
            } catch {
            }
        }

        return fallbackCopy(text);
    };

    const setCopyButtonState = (button, stateLabel, stateClass) => {
        const feedback = button.querySelector("[data-copy-feedback]");
        button.classList.remove("is-copied", "is-failed");
        if (stateClass) {
            button.classList.add(stateClass);
        }

        button.setAttribute("aria-label", stateLabel);
        button.setAttribute("title", stateLabel);
        if (feedback) {
            feedback.textContent = stateLabel;
        }
    };

    document.querySelectorAll("[data-copy-source]").forEach((button) => {
        const defaultLabel = button.dataset.copyLabel || "";
        const doneLabel = button.dataset.copyDone || defaultLabel;
        const failedLabel = button.dataset.copyFailed || defaultLabel;
        let resetTimerId = 0;

        button.addEventListener("click", async (event) => {
            event.preventDefault();
            event.stopPropagation();

            const sourceId = button.dataset.copySource;
            const source = sourceId ? document.getElementById(sourceId) : null;
            const text = source?.textContent || "";
            const success = await copyText(text);

            window.clearTimeout(resetTimerId);
            if (success) {
                setCopyButtonState(button, doneLabel, "is-copied");
            } else {
                setCopyButtonState(button, failedLabel, "is-failed");
            }

            resetTimerId = window.setTimeout(() => {
                setCopyButtonState(button, defaultLabel, "");
            }, 1800);
        });
    });

    document.addEventListener("click", (event) => {
        const target = event.target;
        if (!(target instanceof Element)) {
            return;
        }

        const closeTrigger = target.closest("[data-dropdown-close='true']");
        if (!closeTrigger) {
            return;
        }

        const toggle = closeTrigger
            .closest("[data-twe-dropdown-ref]")
            ?.querySelector("[data-twe-dropdown-toggle-ref]");

        if (toggle instanceof Element) {
            window.setTimeout(() => {
                window.timelineForAudioDropdown?.hide(toggle);
            }, 0);
        }
    });
})();
