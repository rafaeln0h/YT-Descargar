(() => {
    "use strict";

    const state = {
        items: [],
        itemMap: new Map(),
        catalog: { summary: {}, artists: [], albums: [], playlists: [] },
        currentId: "",
        query: "",
        view: "home",
        detail: null,
        queue: [],
        originalQueue: [],
        queueIndex: -1,
        shuffle: localStorage.getItem("ymd.playerShuffle") === "true",
        repeat: localStorage.getItem("ymd.playerRepeat") || "off",
        loading: false,
        lastScan: 0,
        missingIds: new Set(),
    };

    const byId = (id) => document.getElementById(id);
    const audio = () => byId("miniPlayerAudio");
    const video = () => byId("miniPlayerVideo");
    const activeItem = () => state.itemMap.get(state.currentId);
    const activeMedia = () => activeItem()?.kind === "video" ? video() : audio();

    function element(tag, className = "", text = "") {
        const node = document.createElement(tag);
        if (className) node.className = className;
        if (text !== "") node.textContent = text;
        return node;
    }

    function formatBytes(value) {
        const bytes = Number(value || 0);
        if (!bytes) return "";
        const units = ["B", "KB", "MB", "GB"];
        const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
        return `${(bytes / (1024 ** index)).toFixed(index ? 1 : 0)} ${units[index]}`;
    }

    function formatTime(value) {
        const seconds = Math.max(0, Number(value || 0));
        if (!Number.isFinite(seconds)) return "0:00";
        const hours = Math.floor(seconds / 3600);
        const minutes = Math.floor((seconds % 3600) / 60);
        const rest = Math.floor(seconds % 60).toString().padStart(2, "0");
        return hours ? `${hours}:${minutes.toString().padStart(2, "0")}:${rest}` : `${minutes}:${rest}`;
    }

    function showToast(message, timeout = 4200) {
        const toast = byId("libraryToast");
        if (!toast) return;
        toast.textContent = message;
        toast.hidden = false;
        clearTimeout(showToast.timer);
        showToast.timer = window.setTimeout(() => { toast.hidden = true; }, timeout);
    }

    function filteredItems(items = state.items) {
        const query = state.query.trim().toLocaleLowerCase();
        if (!query) return items;
        return items.filter((item) =>
            [item.title, item.artist, item.album_artist, item.album, item.playlist_title, item.name]
                .join(" ")
                .toLocaleLowerCase()
                .includes(query)
        );
    }

    function coverNode(url, label, className = "library-cover") {
        const wrap = element("span", `${className}-wrap`);
        const fallback = element("span", `${className}-fallback`, (label || "♪").trim().slice(0, 1).toUpperCase());
        wrap.appendChild(fallback);
        if (url) {
            const image = element("img", className);
            image.alt = "";
            image.loading = "lazy";
            image.src = url;
            image.addEventListener("load", () => fallback.hidden = true, { once: true });
            image.addEventListener("error", () => image.remove(), { once: true });
            wrap.appendChild(image);
        }
        return wrap;
    }

    function button(label, className, handler) {
        const node = element("button", className, label);
        node.type = "button";
        node.addEventListener("click", handler);
        return node;
    }

    function setView(view, detail = null) {
        state.view = view;
        state.detail = detail;
        byId("libraryViewTabs")?.querySelectorAll("[data-library-view]").forEach((tab) => {
            const selected = tab.dataset.libraryView === view && !detail;
            tab.classList.toggle("is-active", selected);
            tab.setAttribute("aria-selected", String(selected));
        });
        renderLibrary();
    }

    function openLibrary() {
        const tab = document.querySelector('[data-ymd-tab="library"]');
        if (tab) tab.click();
        byId("librarySearch")?.focus();
        if (Date.now() - state.lastScan > 60000) loadLibrary();
    }

    function collectionItems(collection) {
        return (collection?.item_ids || []).map((id) => state.itemMap.get(id)).filter(Boolean);
    }

    function collectionCard(collection, kind) {
        const card = button("", `library-card library-card--${kind}`, () => setView(kind, collection.id));
        card.setAttribute("aria-label", `Abrir ${kind === "artist" ? "artista" : kind === "album" ? "álbum" : "playlist"} ${collection.name || collection.title}`);
        card.appendChild(coverNode(collection.cover_url, collection.name || collection.title, "library-card-cover"));
        const copy = element("span", "library-card-copy");
        copy.appendChild(element("strong", "", collection.name || collection.title));
        const subtitle = kind === "artist"
            ? `${collection.album_count || 0} álbumes · ${collection.count || 0} canciones`
            : [collection.artist || collection.owner, collection.year, `${collection.count || 0} pistas`].filter(Boolean).join(" · ");
        copy.appendChild(element("span", "", subtitle));
        card.appendChild(copy);
        return card;
    }

    function section(title, items, kind, limit = 8) {
        if (!items.length) return null;
        const block = element("section", "library-section");
        const head = element("div", "library-section-head");
        head.appendChild(element("h3", "", title));
        if (items.length > limit) {
            head.appendChild(button("Ver todo", "library-text-button", () => setView(`${kind}s`)));
        }
        block.appendChild(head);
        const grid = element("div", "library-card-grid");
        items.slice(0, limit).forEach((item) => grid.appendChild(collectionCard(item, kind)));
        block.appendChild(grid);
        return block;
    }

    function actionButton(label, variant, items, shuffled = false) {
        const node = button(label, `library-action library-action--${variant}`, () => playCollection(items, shuffled));
        node.disabled = !items.length;
        return node;
    }

    function trackRow(item, index, contextItems) {
        const row = button("", `library-track-row${item.id === state.currentId ? " is-playing" : ""}`, () => playCollection(contextItems, false, item.id));
        row.dataset.mediaId = item.id;
        row.appendChild(element("span", "library-track-number", item.id === state.currentId ? "▶" : String(index + 1)));
        row.appendChild(coverNode(item.artwork_url, item.title, "library-track-cover"));
        const copy = element("span", "library-track-copy");
        copy.appendChild(element("strong", "", item.title || item.name));
        copy.appendChild(element("span", "", [item.artist || item.album_artist, item.album].filter(Boolean).join(" · ")));
        row.appendChild(copy);
        const badges = element("span", "library-track-badges");
        if (item.has_lyrics) badges.appendChild(element("span", "media-badge media-badge--lyrics", "Letra"));
        if (item.kind === "video") badges.appendChild(element("span", "media-badge media-badge--video", "Video"));
        badges.appendChild(element("span", "media-badge", (item.format || "").toUpperCase()));
        row.appendChild(badges);
        row.appendChild(element("span", "library-track-duration", formatTime(item.duration)));
        return row;
    }

    function trackList(items) {
        const list = element("div", "library-track-list");
        items.forEach((item, index) => list.appendChild(trackRow(item, index, items)));
        return list;
    }

    function renderHero() {
        const summary = state.catalog.summary || {};
        const hero = element("section", "library-home-hero");
        const copy = element("div", "library-home-copy");
        copy.appendChild(element("span", "ymd-brand-kicker", "Biblioteca inteligente"));
        copy.appendChild(element("h3", "", "Todo lo que descargaste, listo para sonar"));
        copy.appendChild(element("p", "", `${summary.items || 0} archivos · ${summary.artists || 0} artistas · ${summary.albums || 0} álbumes · ${summary.with_lyrics || 0} con letras`));
        const actions = element("div", "library-actions");
        const songs = state.items.filter((item) => item.kind === "audio");
        actions.append(actionButton("▶ Reproducir todo", "primary", songs));
        actions.append(actionButton("Aleatorio", "secondary", songs, true));
        copy.appendChild(actions);
        hero.appendChild(copy);
        const mosaic = element("div", "library-cover-mosaic");
        state.items.filter((item) => item.artwork_url).slice(0, 4).forEach((item) => mosaic.appendChild(coverNode(item.artwork_url, item.title, "library-mosaic-cover")));
        hero.appendChild(mosaic);
        return hero;
    }

    function renderHome(surface) {
        surface.appendChild(renderHero());
        const artistSection = section("Artistas", state.catalog.artists || [], "artist", 6);
        const albumSection = section("Álbumes", state.catalog.albums || [], "album", 8);
        const playlistSection = section("Playlists", state.catalog.playlists || [], "playlist", 8);
        [artistSection, albumSection, playlistSection].filter(Boolean).forEach((node) => surface.appendChild(node));
        const recent = filteredItems(state.items).slice(0, 12);
        if (recent.length) {
            const block = element("section", "library-section");
            const head = element("div", "library-section-head");
            head.appendChild(element("h3", "", "Recién añadido"));
            block.append(head, trackList(recent));
            surface.appendChild(block);
        }
    }

    function renderGridView(surface, kind) {
        const source = kind === "artists" ? state.catalog.artists : kind === "albums" ? state.catalog.albums : state.catalog.playlists;
        const singular = kind.slice(0, -1);
        const query = state.query.toLocaleLowerCase();
        const results = (source || []).filter((item) => [item.name, item.title, item.artist, item.owner].join(" ").toLocaleLowerCase().includes(query));
        const title = kind === "artists" ? "Artistas" : kind === "albums" ? "Álbumes" : "Playlists";
        const head = element("div", "library-section-head library-view-head");
        head.appendChild(element("h3", "", title));
        head.appendChild(element("span", "", `${results.length} resultados`));
        surface.appendChild(head);
        if (!results.length) {
            const empty = element("div", "library-empty-state library-empty-state--compact");
            empty.appendChild(element("span", "library-empty-icon", state.query ? "⌕" : "♪"));
            empty.appendChild(element("h3", "", state.query ? "No encontramos coincidencias" : `Todavía no hay ${title.toLocaleLowerCase()}`));
            empty.appendChild(element("p", "", state.query
                ? "Prueba con otro título, artista o álbum."
                : kind === "playlists" ? "Las playlists descargadas aparecerán aquí cuando tengan su tag o carpeta de colección." : "Descarga contenido y vuelve a escanear la carpeta."));
            surface.appendChild(empty);
            return;
        }
        const grid = element("div", "library-card-grid library-card-grid--full");
        results.forEach((item) => grid.appendChild(collectionCard(item, singular)));
        surface.appendChild(grid);
    }

    function renderTrackView(surface, kind) {
        const items = filteredItems(state.items.filter((item) => kind === "videos" ? item.kind === "video" : item.kind === "audio"));
        const head = element("div", "library-section-head library-view-head");
        head.appendChild(element("h3", "", kind === "videos" ? "Videos" : "Canciones"));
        const actions = element("div", "library-actions");
        actions.append(actionButton("▶ Reproducir todo", "primary", items));
        actions.append(actionButton("Aleatorio", "secondary", items, true));
        head.appendChild(actions);
        surface.appendChild(head);
        if (!items.length) {
            const empty = element("div", "library-empty-state library-empty-state--compact");
            empty.appendChild(element("span", "library-empty-icon", kind === "videos" ? "▶" : "♪"));
            empty.appendChild(element("h3", "", state.query ? "No encontramos coincidencias" : kind === "videos" ? "Todavía no hay videos" : "Todavía no hay canciones"));
            empty.appendChild(element("p", "", state.query ? "Limpia o cambia la búsqueda para ver más resultados." : "Los nuevos archivos aparecerán aquí después del escaneo."));
            surface.appendChild(empty);
            return;
        }
        surface.appendChild(trackList(items));
    }

    function detailEntity() {
        const source = state.view === "artist" ? state.catalog.artists : state.view === "album" ? state.catalog.albums : state.catalog.playlists;
        return (source || []).find((item) => item.id === state.detail);
    }

    function renderDetail(surface) {
        const entity = detailEntity();
        if (!entity) {
            setView("home");
            return;
        }
        const items = collectionItems(entity);
        const hero = element("section", `library-detail-hero library-detail-hero--${state.view}`);
        hero.appendChild(coverNode(entity.cover_url, entity.name || entity.title, "library-detail-cover"));
        const copy = element("div", "library-detail-copy");
        copy.appendChild(button("← Volver", "library-text-button library-back", () => setView(`${state.view}s`)));
        copy.appendChild(element("span", "ymd-brand-kicker", state.view === "artist" ? "Artista" : state.view === "album" ? "Álbum" : "Playlist"));
        copy.appendChild(element("h3", "", entity.name || entity.title));
        copy.appendChild(element("p", "", [entity.artist || entity.owner, entity.year, `${items.length} pistas`, formatTime(entity.duration)].filter(Boolean).join(" · ")));
        const actions = element("div", "library-actions");
        actions.append(actionButton("▶ Reproducir", "primary", items));
        actions.append(actionButton("Aleatorio", "secondary", items, true));
        copy.appendChild(actions);
        hero.appendChild(copy);
        surface.appendChild(hero);

        if (state.view === "artist") {
            const albumIds = new Set(entity.album_ids || []);
            const artistAlbums = (state.catalog.albums || []).filter((album) => albumIds.has(album.id));
            const block = section("Álbumes", artistAlbums, "album", 50);
            if (block) surface.appendChild(block);
        }
        const tracks = element("section", "library-section");
        const head = element("div", "library-section-head");
        head.appendChild(element("h3", "", state.view === "artist" ? "Canciones" : "Pistas"));
        tracks.append(head, trackList(items));
        surface.appendChild(tracks);
    }

    function renderLibrary() {
        const surface = byId("librarySurface");
        if (!surface) return;
        surface.replaceChildren();
        if (state.loading && !state.items.length) {
            const skeleton = element("div", "library-skeleton");
            for (let index = 0; index < 8; index += 1) skeleton.appendChild(element("span"));
            surface.appendChild(skeleton);
            return;
        }
        if (!state.items.length) {
            const empty = element("div", "library-empty-state");
            empty.appendChild(element("span", "library-empty-icon", "♪"));
            empty.appendChild(element("h3", "", "Tu biblioteca está vacía"));
            empty.appendChild(element("p", "", "Descarga música o revisa la carpeta configurada. El reescaneo ignora archivos eliminados o dañados sin bloquear el resto."));
            empty.appendChild(button("Reescanear carpeta", "library-action library-action--primary", () => loadLibrary(true)));
            surface.appendChild(empty);
            return;
        }
        if (state.detail) return renderDetail(surface);
        if (state.view === "home") return renderHome(surface);
        if (["artists", "albums", "playlists"].includes(state.view)) return renderGridView(surface, state.view);
        return renderTrackView(surface, state.view);
    }

    function updateLibraryStatus(payload) {
        const summary = state.catalog.summary || {};
        const count = byId("libraryCount");
        const root = byId("libraryRoot");
        if (root) root.textContent = payload.root_exists === false ? "La carpeta configurada no está disponible." : payload.root || "Carpeta local";
        if (count) count.textContent = payload.root_exists === false
            ? "Ruta no disponible · revisa Configuración"
            : `${summary.items || 0} archivos · ${summary.artists || 0} artistas · ${summary.albums || 0} álbumes · ${summary.playlists || 0} playlists · ${summary.with_lyrics || 0} con letras`;
    }

    async function loadLibrary(force = false) {
        if (state.loading) return;
        state.loading = true;
        const count = byId("libraryCount");
        if (count) count.textContent = force ? "Reescaneando y depurando referencias…" : "Actualizando biblioteca…";
        renderLibrary();
        try {
            const response = await fetch(force ? "/api/library/rescan" : "/api/library?limit=2000", {
                method: force ? "POST" : "GET",
                cache: "no-store",
            });
            const payload = await response.json();
            if (!response.ok) throw new Error(payload.error || "No se pudo leer la biblioteca");
            state.items = Array.isArray(payload.items) ? payload.items : [];
            state.itemMap = new Map(state.items.map((item) => [item.id, item]));
            state.catalog = {
                summary: payload.summary || {},
                artists: payload.artists || [],
                albums: payload.albums || [],
                playlists: payload.playlists || [],
            };
            state.lastScan = Date.now();
            updateLibraryStatus(payload);
            const lastId = localStorage.getItem("ymd.lastMediaId");
            if (!state.currentId && lastId && state.itemMap.has(lastId)) state.currentId = lastId;
            if (force) showToast(`Biblioteca actualizada: ${state.items.length} archivos disponibles.`);
        } catch (error) {
            if (count) count.textContent = error.message;
            showToast(`No se pudo escanear la biblioteca: ${error.message}`);
        } finally {
            state.loading = false;
            renderLibrary();
            renderQueue();
        }
    }

    function shuffledCopy(ids) {
        const copy = [...ids];
        for (let index = copy.length - 1; index > 0; index -= 1) {
            const target = Math.floor(Math.random() * (index + 1));
            [copy[index], copy[target]] = [copy[target], copy[index]];
        }
        return copy;
    }

    function playCollection(items, shuffled = false, startId = "") {
        const ids = [...new Set(items.filter(Boolean).map((item) => item.id).filter((id) => state.itemMap.has(id)))];
        if (!ids.length) return showToast("No hay archivos reproducibles en esta selección.");
        state.originalQueue = [...ids];
        state.queue = shuffled ? shuffledCopy(ids) : [...ids];
        if (startId && state.queue.includes(startId)) {
            state.queue = [startId, ...state.queue.filter((id) => id !== startId)];
        }
        state.queueIndex = 0;
        state.shuffle = shuffled;
        persistPlayerPreferences();
        playItem(state.itemMap.get(state.queue[0]));
        renderQueue();
    }

    function updatePlayerArtwork(item) {
        const image = byId("miniPlayerCover");
        const fallback = byId("miniPlayerCoverPlaceholder");
        if (!image || !fallback) return;
        if (!item.artwork_url) {
            image.hidden = true;
            image.removeAttribute("src");
            fallback.hidden = false;
            return;
        }
        image.hidden = false;
        image.src = item.artwork_url;
        fallback.hidden = true;
        image.onerror = () => { image.hidden = true; fallback.hidden = false; };
    }

    function configureMediaSession(item, media) {
        if (!("mediaSession" in navigator) || !("MediaMetadata" in window)) return;
        navigator.mediaSession.metadata = new MediaMetadata({
            title: item.title || item.name || "Sin título",
            artist: item.artist || item.album_artist || "YT-Descargar",
            album: item.album || "Biblioteca local",
            artwork: item.artwork_url ? [{ src: item.artwork_url }] : [],
        });
        const handlers = {
            play: () => media.play(),
            pause: () => media.pause(),
            stop: stopPlayer,
            previoustrack: previousTrack,
            nexttrack: nextTrack,
            seekbackward: (details) => { media.currentTime = Math.max(0, media.currentTime - (details.seekOffset || 10)); },
            seekforward: (details) => { media.currentTime = Math.min(media.duration || Infinity, media.currentTime + (details.seekOffset || 10)); },
            seekto: (details) => { if (Number.isFinite(details.seekTime)) media.currentTime = details.seekTime; },
        };
        Object.entries(handlers).forEach(([action, handler]) => {
            try { navigator.mediaSession.setActionHandler(action, handler); } catch (_error) { /* Optional action. */ }
        });
    }

    function playItem(item) {
        if (!item) return;
        const shell = byId("miniPlayer");
        const audioNode = audio();
        const videoNode = video();
        if (!shell || !audioNode || !videoNode) return;
        [audioNode, videoNode].forEach((media) => {
            media.pause();
            media.removeAttribute("src");
            media.load();
        });
        const media = item.kind === "video" ? videoNode : audioNode;
        byId("videoStage").hidden = item.kind !== "video";
        media.src = item.stream_url;
        media.volume = Number(localStorage.getItem("ymd.playerVolume") || 0.8);
        media.load();
        state.currentId = item.id;
        const queuePosition = state.queue.indexOf(item.id);
        if (queuePosition >= 0) state.queueIndex = queuePosition;
        shell.hidden = false;
        byId("miniPlayerTitle").textContent = item.title || item.name;
        byId("miniPlayerSubtitle").textContent = [item.artist || item.album_artist, item.album].filter(Boolean).join(" · ");
        byId("miniPlayerState").textContent = item.kind === "video" ? "Reproduciendo video" : "Reproduciendo desde tu biblioteca";
        const lyricsButton = byId("playerLyrics");
        lyricsButton.disabled = !item.has_lyrics;
        lyricsButton.classList.toggle("has-lyrics", Boolean(item.has_lyrics));
        updatePlayerArtwork(item);
        configureMediaSession(item, media);
        localStorage.setItem("ymd.lastMediaId", item.id);
        media.play().catch(() => showToast("Pulsa reproducir para iniciar este archivo."));
        updatePlayerButtons();
        renderLibrary();
        renderQueue();
    }

    function nextTrack(fromEnded = false) {
        const media = activeMedia();
        if (fromEnded && state.repeat === "one" && media) {
            media.currentTime = 0;
            media.play();
            return;
        }
        let nextIndex = state.queueIndex + 1;
        if (nextIndex >= state.queue.length) {
            if (state.repeat === "all" && state.queue.length) nextIndex = 0;
            else return stopAtQueueEnd();
        }
        state.queueIndex = nextIndex;
        playItem(state.itemMap.get(state.queue[nextIndex]));
    }

    function previousTrack() {
        const media = activeMedia();
        if (media && media.currentTime > 3) {
            media.currentTime = 0;
            return;
        }
        const previousIndex = state.queueIndex - 1;
        if (previousIndex < 0) {
            if (state.repeat === "all" && state.queue.length) state.queueIndex = state.queue.length - 1;
            else return;
        } else state.queueIndex = previousIndex;
        playItem(state.itemMap.get(state.queue[state.queueIndex]));
    }

    function stopAtQueueEnd() {
        const media = activeMedia();
        if (media) media.pause();
        byId("miniPlayerState").textContent = "Cola finalizada";
        updatePlayerButtons();
    }

    function stopPlayer() {
        [audio(), video()].filter(Boolean).forEach((media) => {
            media.pause();
            media.removeAttribute("src");
            media.load();
        });
        byId("miniPlayer").hidden = true;
        byId("videoStage").hidden = true;
        closeSidePanels();
    }

    function togglePlayback() {
        const media = activeMedia();
        if (!media || !media.src) return;
        if (media.paused) media.play(); else media.pause();
    }

    function toggleShuffle() {
        if (!state.queue.length) return;
        const current = state.currentId;
        state.shuffle = !state.shuffle;
        if (state.shuffle) {
            state.queue = [current, ...shuffledCopy(state.queue.filter((id) => id !== current))];
            state.queueIndex = 0;
        } else {
            state.queue = [...state.originalQueue].filter((id) => state.itemMap.has(id));
            state.queueIndex = Math.max(0, state.queue.indexOf(current));
        }
        persistPlayerPreferences();
        updatePlayerButtons();
        renderQueue();
    }

    function cycleRepeat() {
        state.repeat = state.repeat === "off" ? "all" : state.repeat === "all" ? "one" : "off";
        persistPlayerPreferences();
        updatePlayerButtons();
        showToast(state.repeat === "one" ? "Repetir canción" : state.repeat === "all" ? "Repetir cola" : "Repetición desactivada");
    }

    function persistPlayerPreferences() {
        localStorage.setItem("ymd.playerShuffle", String(state.shuffle));
        localStorage.setItem("ymd.playerRepeat", state.repeat);
    }

    function updatePlayerButtons() {
        const media = activeMedia();
        const play = byId("playerPlayPause");
        if (play) {
            const paused = !media || media.paused;
            play.textContent = paused ? "▶" : "❚❚";
            play.setAttribute("aria-label", paused ? "Reproducir" : "Pausar");
        }
        const shuffle = byId("playerShuffle");
        shuffle?.classList.toggle("is-active", state.shuffle);
        shuffle?.setAttribute("aria-pressed", String(state.shuffle));
        const repeat = byId("playerRepeat");
        repeat?.classList.toggle("is-active", state.repeat !== "off");
        if (repeat) {
            repeat.textContent = state.repeat === "one" ? "↻1" : "↻";
            repeat.setAttribute("aria-label", state.repeat === "one" ? "Repetir una canción" : state.repeat === "all" ? "Repetir cola" : "Repetición desactivada");
        }
    }

    function updateProgress(media) {
        const duration = Number.isFinite(media.duration) ? media.duration : 0;
        const current = Number.isFinite(media.currentTime) ? media.currentTime : 0;
        byId("playerElapsed").textContent = formatTime(current);
        byId("playerDuration").textContent = formatTime(duration);
        const seek = byId("playerSeek");
        seek.max = String(duration || 100);
        seek.value = String(current);
        if ("mediaSession" in navigator && duration > 0) {
            try { navigator.mediaSession.setPositionState({ duration, playbackRate: media.playbackRate || 1, position: Math.min(current, duration) }); } catch (_error) { /* Optional. */ }
        }
    }

    function renderQueue() {
        const list = byId("playerQueueList");
        if (!list) return;
        list.replaceChildren();
        if (!state.queue.length) {
            list.appendChild(element("p", "library-empty", "La cola se crea al reproducir una canción, álbum, artista o playlist."));
            return;
        }
        state.queue.forEach((id, index) => {
            const item = state.itemMap.get(id);
            if (!item) return;
            const row = button("", `queue-track${id === state.currentId ? " is-playing" : ""}`, () => playItem(item));
            row.appendChild(element("span", "queue-track-index", id === state.currentId ? "▶" : String(index + 1)));
            row.appendChild(coverNode(item.artwork_url, item.title, "queue-track-cover"));
            const copy = element("span", "queue-track-copy");
            copy.append(element("strong", "", item.title || item.name), element("span", "", [item.artist, item.album].filter(Boolean).join(" · ")));
            row.appendChild(copy);
            list.appendChild(row);
        });
    }

    function closeSidePanels() {
        [byId("playerQueuePanel"), byId("playerLyricsPanel")].filter(Boolean).forEach((panel) => panel.hidden = true);
    }

    function togglePanel(panel) {
        const willOpen = panel.hidden;
        closeSidePanels();
        panel.hidden = !willOpen;
    }

    async function openLyrics() {
        const item = activeItem();
        if (!item?.lyrics_url) return;
        const panel = byId("playerLyricsPanel");
        const content = byId("lyricsContent");
        byId("lyricsTitle").textContent = item.title || "Letra";
        content.textContent = "Cargando letra…";
        closeSidePanels();
        panel.hidden = false;
        try {
            const response = await fetch(item.lyrics_url, { cache: "no-store" });
            const payload = await response.json();
            if (!response.ok) throw new Error(payload.error || "No se pudo leer la letra");
            content.textContent = payload.lyrics;
        } catch (error) {
            content.textContent = error.message;
        }
    }

    async function handleMediaError() {
        const item = activeItem();
        if (!item || state.missingIds.has(item.id)) return;
        state.missingIds.add(item.id);
        showToast(`“${item.title || item.name}” ya no está disponible. Se omitirá y la biblioteca se actualizará.`);
        const removedIndex = state.queue.indexOf(item.id);
        state.queue = state.queue.filter((id) => id !== item.id);
        state.originalQueue = state.originalQueue.filter((id) => id !== item.id);
        state.queueIndex = Math.max(-1, removedIndex - 1);
        state.items = state.items.filter((entry) => entry.id !== item.id);
        state.itemMap.delete(item.id);
        renderQueue();
        renderLibrary();
        if (state.queue.length) nextTrack(); else stopPlayer();
        window.setTimeout(() => loadLibrary(true), 500);
    }

    function bindMedia(media) {
        media.addEventListener("loadedmetadata", () => updateProgress(media));
        media.addEventListener("timeupdate", () => updateProgress(media));
        media.addEventListener("play", () => {
            updatePlayerButtons();
            if ("mediaSession" in navigator) navigator.mediaSession.playbackState = "playing";
        });
        media.addEventListener("pause", () => {
            updatePlayerButtons();
            if ("mediaSession" in navigator) navigator.mediaSession.playbackState = "paused";
        });
        media.addEventListener("ended", () => nextTrack(true));
        media.addEventListener("error", handleMediaError);
    }

    function bindKeyboard() {
        document.addEventListener("keydown", (event) => {
            const tag = event.target?.tagName?.toLowerCase();
            if (["input", "textarea", "select", "button"].includes(tag)) return;
            if (event.code === "Space") { event.preventDefault(); togglePlayback(); }
            if (event.key.toLowerCase() === "n") nextTrack();
            if (event.key.toLowerCase() === "p") previousTrack();
            if (event.key.toLowerCase() === "m") byId("playerMute")?.click();
            const media = activeMedia();
            if (event.key === "ArrowRight" && media) media.currentTime = Math.min(media.duration || Infinity, media.currentTime + 5);
            if (event.key === "ArrowLeft" && media) media.currentTime = Math.max(0, media.currentTime - 5);
            if (event.key === "Escape") { closeSidePanels(); byId("videoStage").hidden = true; }
        });
    }

    function init() {
        byId("libraryViewTabs")?.querySelectorAll("[data-library-view]").forEach((tab) => {
            tab.addEventListener("click", () => setView(tab.dataset.libraryView));
        });
        byId("libraryRefresh")?.addEventListener("click", () => loadLibrary(true));
        byId("librarySearch")?.addEventListener("input", (event) => {
            state.query = event.target.value || "";
            renderLibrary();
        });
        byId("libraryToggle")?.addEventListener("click", openLibrary);
        byId("miniPlayerClose")?.addEventListener("click", stopPlayer);
        byId("playerPlayPause")?.addEventListener("click", togglePlayback);
        byId("playerPrevious")?.addEventListener("click", previousTrack);
        byId("playerNext")?.addEventListener("click", () => nextTrack());
        byId("playerShuffle")?.addEventListener("click", toggleShuffle);
        byId("playerRepeat")?.addEventListener("click", cycleRepeat);
        byId("playerQueue")?.addEventListener("click", () => togglePanel(byId("playerQueuePanel")));
        byId("playerLyrics")?.addEventListener("click", openLyrics);
        byId("playerMute")?.addEventListener("click", () => {
            const media = activeMedia();
            if (!media) return;
            media.muted = !media.muted;
            byId("playerMute").textContent = media.muted ? "🔇" : "🔊";
        });
        const volume = Number(localStorage.getItem("ymd.playerVolume") || 0.8);
        byId("playerVolume").value = String(volume);
        byId("playerVolume")?.addEventListener("input", (event) => {
            const value = Number(event.target.value);
            [audio(), video()].filter(Boolean).forEach((media) => { media.volume = value; media.muted = false; });
            byId("playerMute").textContent = value === 0 ? "🔇" : "🔊";
            localStorage.setItem("ymd.playerVolume", String(value));
        });
        byId("playerSeek")?.addEventListener("input", (event) => {
            const media = activeMedia();
            if (media && Number.isFinite(Number(event.target.value))) media.currentTime = Number(event.target.value);
        });
        byId("videoStageClose")?.addEventListener("click", () => { byId("videoStage").hidden = true; });
        document.querySelectorAll("[data-close-player-panel]").forEach((node) => node.addEventListener("click", closeSidePanels));
        document.querySelector('[data-ymd-tab="library"]')?.addEventListener("click", () => {
            if (Date.now() - state.lastScan > 60000) loadLibrary();
        });
        bindMedia(audio());
        bindMedia(video());
        bindKeyboard();
        updatePlayerButtons();
        loadLibrary();
        let focusTimer = 0;
        window.addEventListener("focus", () => {
            clearTimeout(focusTimer);
            focusTimer = window.setTimeout(() => {
                if (Date.now() - state.lastScan > 60000) loadLibrary();
            }, 500);
        });
    }

    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init, { once: true });
    else init();
})();
