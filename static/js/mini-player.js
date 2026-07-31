(() => {
    "use strict";

    const state = {
        items: [],
        currentId: "",
        query: "",
    };

    const byId = (id) => document.getElementById(id);

    function formatBytes(value) {
        const bytes = Number(value || 0);
        if (!bytes) return "";
        const units = ["B", "KB", "MB", "GB"];
        const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
        return `${(bytes / (1024 ** index)).toFixed(index ? 1 : 0)} ${units[index]}`;
    }

    function setDrawer(open) {
        const drawer = byId("libraryDrawer");
        if (!drawer) return;
        drawer.hidden = !open;
        if (open) {
            byId("librarySearch")?.focus();
            loadLibrary();
        }
    }

    function visibleItems() {
        const query = state.query.trim().toLocaleLowerCase();
        if (!query) return state.items;
        return state.items.filter((item) =>
            [item.title, item.artist, item.album, item.name, item.relative_path]
                .join(" ")
                .toLocaleLowerCase()
                .includes(query)
        );
    }

    function renderLibrary() {
        const list = byId("libraryList");
        const count = byId("libraryCount");
        if (!list) return;
        list.replaceChildren();
        const items = visibleItems();
        if (count) count.textContent = `${items.length} archivos`;

        if (!items.length) {
            const empty = document.createElement("div");
            empty.className = "library-empty";
            empty.textContent = "No hay archivos reproducibles en la carpeta configurada. Descarga algo o revisa la ruta en Configuración.";
            list.appendChild(empty);
            return;
        }

        items.forEach((item) => {
            const button = document.createElement("button");
            button.type = "button";
            button.className = `library-item${item.id === state.currentId ? " is-playing" : ""}`;
            button.addEventListener("click", () => playItem(item));

            const icon = document.createElement("span");
            icon.className = "library-item-icon";
            icon.textContent = item.kind === "video" ? "▶" : "♪";

            const copy = document.createElement("span");
            copy.className = "library-item-copy";
            const title = document.createElement("strong");
            title.textContent = item.title || item.name;
            const subtitle = document.createElement("span");
            subtitle.textContent = [item.artist, item.album, formatBytes(item.size)].filter(Boolean).join(" · ");
            copy.append(title, subtitle);

            const format = document.createElement("span");
            format.className = "library-item-format";
            format.textContent = (item.format || "").toUpperCase();
            button.append(icon, copy, format);
            list.appendChild(button);
        });
    }

    function playItem(item) {
        const shell = byId("miniPlayer");
        const audio = byId("miniPlayerAudio");
        const video = byId("miniPlayerVideo");
        if (!shell || !audio || !video) return;

        audio.pause();
        video.pause();
        audio.removeAttribute("src");
        video.removeAttribute("src");
        const media = item.kind === "video" ? video : audio;
        audio.hidden = item.kind === "video";
        video.hidden = item.kind !== "video";
        media.src = item.stream_url;
        media.load();
        media.play().catch(() => {
            // Browser autoplay policies may require the user to press play.
        });

        state.currentId = item.id;
        shell.hidden = false;
        byId("miniPlayerTitle").textContent = item.title || item.name;
        byId("miniPlayerSubtitle").textContent =
            [item.artist, item.album, item.relative_path].filter(Boolean).join(" · ");
        localStorage.setItem("ymd.lastMediaId", item.id);
        renderLibrary();
    }

    async function loadLibrary() {
        const count = byId("libraryCount");
        if (count) count.textContent = "Actualizando…";
        try {
            const response = await fetch("/api/library?limit=300", { cache: "no-store" });
            const payload = await response.json();
            if (!response.ok) throw new Error(payload.error || "No se pudo leer la biblioteca");
            state.items = Array.isArray(payload.items) ? payload.items : [];
            const lastId = localStorage.getItem("ymd.lastMediaId");
            if (!state.currentId && lastId && state.items.some((item) => item.id === lastId)) {
                state.currentId = lastId;
            }
        } catch (error) {
            state.items = [];
            if (count) count.textContent = error.message;
        }
        renderLibrary();
    }

    function init() {
        byId("libraryToggle")?.addEventListener("click", () => setDrawer(true));
        byId("libraryToggleLauncher")?.addEventListener("click", () => setDrawer(true));
        byId("libraryClose")?.addEventListener("click", () => setDrawer(false));
        byId("libraryRefresh")?.addEventListener("click", loadLibrary);
        byId("miniPlayerClose")?.addEventListener("click", () => {
            byId("miniPlayerAudio")?.pause();
            byId("miniPlayerVideo")?.pause();
            byId("miniPlayer").hidden = true;
        });
        byId("librarySearch")?.addEventListener("input", (event) => {
            state.query = event.target.value || "";
            renderLibrary();
        });
        document.addEventListener("keydown", (event) => {
            if (event.key === "Escape") setDrawer(false);
        });
        window.addEventListener("focus", loadLibrary);
        loadLibrary();
        window.setInterval(loadLibrary, 30000);
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init, { once: true });
    } else {
        init();
    }
})();
