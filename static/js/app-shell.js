(() => {
    "use strict";

    const PREF_KEY = "ymd.notificationPreferences";
    const STATE_KEY = "ymd.notificationQueueStates";
    const UPDATE_DISMISS_KEY = "ymd.dismissedUpdate";
    const DEFAULTS = {
        enabled: false,
        completed: true,
        errors: true,
        quietWhilePlaying: true,
    };
    let initialized = false;
    let previousActive = 0;

    function readJson(key, fallback) {
        try {
            return { ...fallback, ...JSON.parse(localStorage.getItem(key) || "{}") };
        } catch (_error) {
            return { ...fallback };
        }
    }

    function preferences() {
        return readJson(PREF_KEY, DEFAULTS);
    }

    function savePreferences(patch) {
        const next = { ...preferences(), ...patch };
        localStorage.setItem(PREF_KEY, JSON.stringify(next));
        window.dispatchEvent(new CustomEvent("ymd:notification-settings", { detail: next }));
        return next;
    }

    function toast(message, tone = "info") {
        let region = document.getElementById("ymdToastRegion");
        if (!region) {
            region = document.createElement("div");
            region.id = "ymdToastRegion";
            region.className = "ymd-toast-region";
            region.setAttribute("aria-live", "polite");
            document.body.appendChild(region);
        }
        const item = document.createElement("div");
        item.className = `ymd-toast ymd-toast-${tone}`;
        item.textContent = message;
        region.appendChild(item);
        window.setTimeout(() => item.classList.add("is-visible"), 20);
        window.setTimeout(() => {
            item.classList.remove("is-visible");
            window.setTimeout(() => item.remove(), 240);
        }, 4200);
    }

    function mediaIsPlaying() {
        return Array.from(document.querySelectorAll("audio, video")).some((media) => !media.paused && !media.ended);
    }

    async function serviceWorkerRegistration() {
        if (!("serviceWorker" in navigator)) return null;
        try {
            return await navigator.serviceWorker.register("/service-worker.js", { scope: "/" });
        } catch (error) {
            console.warn("No se pudo registrar el soporte de notificaciones:", error);
            return null;
        }
    }

    async function requestNotifications() {
        if (!("Notification" in window)) {
            toast("Este navegador no admite notificaciones del sistema.", "error");
            return "unsupported";
        }
        const permission = await Notification.requestPermission();
        savePreferences({ enabled: permission === "granted" });
        toast(
            permission === "granted" ? "Notificaciones inteligentes activadas." : "Las notificaciones siguen desactivadas.",
            permission === "granted" ? "success" : "info",
        );
        return permission;
    }

    async function systemNotification(title, options = {}) {
        const prefs = preferences();
        if (!prefs.enabled || !("Notification" in window) || Notification.permission !== "granted") return;
        if (prefs.quietWhilePlaying && mediaIsPlaying() && options.tone !== "error") return;

        const dedupeKey = `ymd.notification.${options.tag || title}`;
        const lastShown = Number(localStorage.getItem(dedupeKey) || 0);
        if (Date.now() - lastShown < 45000) return;
        localStorage.setItem(dedupeKey, String(Date.now()));

        const registration = await serviceWorkerRegistration();
        const notificationOptions = {
            body: options.body || "",
            icon: "/static/icons/ymd.svg",
            badge: "/static/icons/ymd.svg",
            tag: options.tag || "ymd-status",
            renotify: false,
            data: { url: options.url || "/#activity" },
        };
        if (registration?.showNotification) {
            await registration.showNotification(title, notificationOptions);
        } else {
            new Notification(title, notificationOptions);
        }
    }

    function normalizedStatus(item) {
        const value = String(item.status || "").toLowerCase();
        if (["completed", "completado"].includes(value)) return "completed";
        if (["error"].includes(value)) return "error";
        if (["cancelled", "cancelado"].includes(value)) return "cancelled";
        if (["pending", "starting", "running", "iniciando", "analizando", "descargando", "pausado"].includes(value)) return "active";
        return value;
    }

    async function pollQueueEvents() {
        try {
            const [queueResponse, batchResponse] = await Promise.all([
                fetch("/api/queue", { cache: "no-store" }),
                fetch("/api/batch-queue", { cache: "no-store" }),
            ]);
            const queue = queueResponse.ok ? await queueResponse.json() : [];
            const batch = batchResponse.ok ? await batchResponse.json() : [];
            const items = [
                ...queue.map((item) => ({ ...item, eventId: `queue-${item.queue_id}` })),
                ...batch.map((item) => ({ ...item, eventId: `batch-${item.job_id}` })),
            ];
            const previous = readJson(STATE_KEY, {});
            const current = {};
            let active = 0;
            let completedTransitions = 0;
            const hasPreviousSnapshot = Object.keys(previous).length > 0;
            if (!initialized && hasPreviousSnapshot) {
                previousActive = Object.values(previous).filter((status) => status === "active").length;
            }

            for (const item of items) {
                const status = normalizedStatus(item);
                current[item.eventId] = status;
                if (status === "active") active += 1;
                const oldStatus = previous[item.eventId];
                if ((!initialized && !hasPreviousSnapshot) || !oldStatus || oldStatus === status) continue;

                if (status === "error" && preferences().errors) {
                    toast(`${item.title || item.label || "Descarga"}: ${item.message || "ocurrió un error"}`, "error");
                    await systemNotification("Error de descarga", {
                        body: `${item.title || item.label || "Tarea"}: ${item.message || "Revisa la cola"}`,
                        tag: `error-${item.eventId}`,
                        tone: "error",
                    });
                } else if (status === "completed") {
                    completedTransitions += 1;
                }
            }

            if (initialized && completedTransitions && preferences().completed) {
                const allDone = previousActive > 0 && active === 0;
                const message = allDone
                    ? "Terminó toda la cola de descargas."
                    : `${completedTransitions} descarga(s) completada(s).`;
                toast(message, "success");
                await systemNotification(allDone ? "Lista completa" : "Descarga completada", {
                    body: message,
                    tag: allDone ? "queue-complete" : `complete-${Date.now()}`,
                });
            }

            initialized = true;
            previousActive = active;
            localStorage.setItem(STATE_KEY, JSON.stringify(current));
        } catch (error) {
            console.debug("La cola no está disponible temporalmente:", error);
        }
    }

    function notifyLinkDetected(label) {
        toast(`Enlace detectado${label ? `: ${label}` : ""}. Listo para revisar.`, "success");
    }

    function showUpdateBanner(payload) {
        const release = payload?.latest_release;
        if (!payload?.update_available || !release?.tag || !release?.url) return;
        if (localStorage.getItem(UPDATE_DISMISS_KEY) === release.tag) return;
        if (document.getElementById("ymdUpdateBanner")) return;

        const banner = document.createElement("aside");
        banner.id = "ymdUpdateBanner";
        banner.className = "ymd-update-banner";
        banner.setAttribute("role", "status");

        const copy = document.createElement("div");
        const title = document.createElement("strong");
        title.textContent = `Actualizacion ${release.tag} disponible`;
        const description = document.createElement("span");
        description.textContent = ` Tienes ${payload.current_version}. Se recomienda revisar la nueva version antes de instalarla.`;
        copy.append(title, description);

        const actions = document.createElement("div");
        actions.className = "ymd-update-actions";
        const link = document.createElement("a");
        link.href = release.url;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        link.textContent = "Ver cambios";
        const dismiss = document.createElement("button");
        dismiss.type = "button";
        dismiss.setAttribute("aria-label", "Ocultar esta actualizacion");
        dismiss.textContent = "Ahora no";
        dismiss.addEventListener("click", () => {
            localStorage.setItem(UPDATE_DISMISS_KEY, release.tag);
            banner.remove();
        });
        actions.append(link, dismiss);
        banner.append(copy, actions);
        document.body.appendChild(banner);
    }

    async function checkForUpdates() {
        try {
            const response = await fetch("/api/system/update", { cache: "no-store" });
            if (!response.ok) return;
            showUpdateBanner(await response.json());
        } catch (error) {
            console.debug("No se pudo comprobar actualizaciones:", error);
        }
    }

    function initPageTabs() {
        const tablist = document.querySelector("[data-ymd-tablist]");
        if (!tablist) return;
        const tabs = Array.from(tablist.querySelectorAll("[data-ymd-tab]"));
        const panels = Array.from(document.querySelectorAll("[data-ymd-panel]"));
        if (!tabs.length || !panels.length) return;

        const knownTabs = new Set(tabs.map((tab) => tab.dataset.ymdTab));
        const defaultTab = tabs.find((tab) => tab.classList.contains("is-active"))?.dataset.ymdTab
            || tabs[0].dataset.ymdTab;

        const activate = (name, { updateHash = true } = {}) => {
            const target = knownTabs.has(name) ? name : defaultTab;
            const render = () => {
                tabs.forEach((tab) => {
                    const selected = tab.dataset.ymdTab === target;
                    tab.classList.toggle("is-active", selected);
                    tab.setAttribute("aria-selected", String(selected));
                    tab.tabIndex = selected ? 0 : -1;
                });
                panels.forEach((panel) => {
                    const selected = panel.dataset.ymdPanel === target;
                    panel.hidden = !selected;
                    panel.classList.toggle("is-active", selected);
                });
            };
            if (document.startViewTransition) document.startViewTransition(render);
            else render();
            if (updateHash && location.hash !== `#${target}`) history.replaceState(null, "", `#${target}`);
        };

        tabs.forEach((tab, index) => {
            tab.addEventListener("click", () => activate(tab.dataset.ymdTab));
            tab.addEventListener("keydown", (event) => {
                if (!["ArrowLeft", "ArrowRight"].includes(event.key)) return;
                event.preventDefault();
                const direction = event.key === "ArrowRight" ? 1 : -1;
                const next = tabs[(index + direction + tabs.length) % tabs.length];
                next.focus();
                activate(next.dataset.ymdTab);
            });
        });
        tablist.querySelectorAll("[data-ymd-action='library']").forEach((button) => {
            button.addEventListener("click", () => {
                const drawer = document.getElementById("libraryDrawer");
                if (drawer) drawer.hidden = false;
                document.getElementById("libraryRefresh")?.click();
                document.getElementById("librarySearch")?.focus();
            });
        });
        window.addEventListener("hashchange", () => activate(location.hash.slice(1), { updateHash: false }));
        activate(location.hash.slice(1), { updateHash: false });
    }

    function init() {
        serviceWorkerRegistration();
        document.body.classList.add("ymd-ready");
        initPageTabs();
        document.querySelectorAll("[data-enable-notifications]").forEach((button) => {
            button.addEventListener("click", requestNotifications);
        });
        pollQueueEvents();
        checkForUpdates();
        window.setInterval(pollQueueEvents, 5000);
    }

    window.YMDApp = {
        getNotificationPreferences: preferences,
        notifyLinkDetected,
        requestNotifications,
        saveNotificationPreferences: savePreferences,
        checkForUpdates,
        toast,
    };

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init, { once: true });
    } else {
        init();
    }
})();
