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

    function canonicalQueueUrl(rawUrl) {
        const raw = String(rawUrl || "").trim();
        if (!raw) return "";
        try {
            const parsed = new URL(raw, window.location.origin);
            const important = new URLSearchParams();
            ["v", "list"].forEach((key) => {
                if (parsed.searchParams.get(key)) important.set(key, parsed.searchParams.get(key));
            });
            const pathname = parsed.pathname.replace(/\/+$/, "");
            const query = important.toString();
            return `${parsed.hostname.toLowerCase()}${pathname}${query ? `?${query}` : ""}`;
        } catch (_error) {
            return raw.toLowerCase();
        }
    }

    function queueSignature(item, local = false) {
        if (local && item.signature) return String(item.signature);
        const payload = item.request_payload || item.payload || {};
        const type = String(item.type || item.kind || "single").toLowerCase();
        const sourceUrl = item.source_url || payload.url || item.url || "";
        return `${type}|${canonicalQueueUrl(sourceUrl)}`;
    }

    function timestampMs(item, local = false) {
        const explicit = local ? (item.createdAt || item.updatedAt) : (item.updated_at || item.created_at);
        const numeric = Number(explicit || 0);
        if (Number.isFinite(numeric) && numeric > 0) return numeric;
        const parsed = Date.parse(explicit || "");
        if (Number.isFinite(parsed)) return parsed;
        if (local) {
            const match = String(item.uiId || "").match(/^job_(\d+)/);
            if (match) return Number(match[1]);
        }
        return 0;
    }

    function reconcileLocalPending(backendItems = [], historyItems = []) {
        let saved;
        try {
            saved = JSON.parse(localStorage.getItem("ymd.pendingQueue") || "[]");
        } catch (_error) {
            return { jobs: [], removed: 0 };
        }
        if (!Array.isArray(saved) || !saved.length) return { jobs: Array.isArray(saved) ? saved : [], removed: 0 };

        const activeSignatures = new Set();
        const completedAt = new Map();
        [...backendItems, ...historyItems].forEach((item) => {
            const signature = queueSignature(item);
            if (!signature.endsWith("|")) {
                const status = normalizedStatus(item);
                if (status === "active") activeSignatures.add(signature);
                if (status === "completed") {
                    completedAt.set(signature, Math.max(completedAt.get(signature) || 0, timestampMs(item)));
                }
            }
        });

        const jobs = saved.filter((job) => {
            const status = String(job.localStatus || "pending").toLowerCase();
            if (!["pending", "processing", "paused"].includes(status)) return true;
            const signature = queueSignature(job, true);
            if (activeSignatures.has(signature)) return false;
            const backendTime = completedAt.get(signature);
            if (backendTime === undefined) return true;
            const localTime = timestampMs(job, true);
            return localTime > 0 && backendTime > 0 && localTime > backendTime;
        });
        const removed = saved.length - jobs.length;
        if (removed) {
            localStorage.setItem("ymd.pendingQueue", JSON.stringify(jobs));
            window.dispatchEvent(new CustomEvent("ymd:pending-queue-reconciled", {
                detail: { jobs, removed },
            }));
        }
        return { jobs, removed };
    }

    function updateActivityIndicator(items) {
        const activeItems = items.filter((item) => normalizedStatus(item) === "active");
        let localPending = 0;
        try {
            const saved = JSON.parse(localStorage.getItem("ymd.pendingQueue") || "[]");
            localPending = Array.isArray(saved)
                ? saved.filter((item) => String(item.localStatus || "pending") === "pending").length
                : 0;
        } catch (_error) {
            localPending = 0;
        }
        const totalAttention = activeItems.length + localPending;
        const tabBadge = document.getElementById("downloadTabBadge");
        if (tabBadge) {
            tabBadge.textContent = String(totalAttention);
            tabBadge.hidden = totalAttention === 0;
            tabBadge.setAttribute("aria-label", `${activeItems.length} descargas activas y ${localPending} pendientes`);
        }

        let popout = document.getElementById("ymdDownloadPopout");
        if (!totalAttention) {
            popout?.remove();
            return;
        }
        if (!popout) {
            popout = document.createElement("a");
            popout.id = "ymdDownloadPopout";
            popout.className = "ymd-download-popout";
            popout.href = "/#activity";
            popout.innerHTML = '<span class="ymd-download-pulse" aria-hidden="true"></span><span><strong></strong><small></small></span>';
            document.body.appendChild(popout);
        }
        const first = activeItems[0] || {};
        const progress = Number(first.progress || 0);
        popout.querySelector("strong").textContent = activeItems.length
            ? (activeItems.length === 1 ? "1 descarga activa" : `${activeItems.length} descargas activas`)
            : (localPending === 1 ? "1 tarea pendiente" : `${localPending} tareas pendientes`);
        popout.querySelector("small").textContent = activeItems.length
            ? `${first.title || first.label || "Procesando"}${progress ? ` · ${progress}%` : ""} · Ver progreso`
            : "Falta pulsar Iniciar cola · Ir a Descargas";
    }

    async function pollQueueEvents() {
        try {
            const [queueResponse, batchResponse, historyResponse] = await Promise.all([
                fetch("/api/queue", { cache: "no-store" }),
                fetch("/api/batch-queue", { cache: "no-store" }),
                fetch("/api/history", { cache: "no-store" }),
            ]);
            const queue = queueResponse.ok ? await queueResponse.json() : [];
            const batch = batchResponse.ok ? await batchResponse.json() : [];
            const history = historyResponse.ok ? await historyResponse.json() : [];
            const items = [
                ...queue.map((item) => ({ ...item, eventId: `queue-${item.queue_id}` })),
                ...batch.map((item) => ({ ...item, eventId: `batch-${item.job_id}` })),
            ];
            reconcileLocalPending(items, history);
            updateActivityIndicator(items);
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
        refreshDownloadStatus: pollQueueEvents,
        reconcileLocalPending,
        toast,
    };

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init, { once: true });
    } else {
        init();
    }
})();
