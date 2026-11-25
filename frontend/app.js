
const $ = id => document.getElementById(id);

let citizenMap, citizenMarker, adminMap;
let wardLayer, historicalLayer, liveLayer;
let charts = {};

const BLR = [12.9716, 77.5946];
const API = "";

// ---------------- SHARED HELPERS ----------------

function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, c => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;",
        '"': "&quot;", "'": "&#39;"
    }[c]));
}

function escapeAttribute(value) {
    return escapeHtml(value).replace(/`/g, "&#96;");
}

async function api(url, options = {}) {
    const response = await fetch(API + url, options);
    const contentType = response.headers.get("content-type") || "";
    let data = {};
    if (contentType.includes("application/json")) {
        try { data = await response.json(); } catch { data = {}; }
    } else {
        const text = await response.text();
        data = { detail: text.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim().slice(0, 240) };
    }
    if (!response.ok) {
        throw new Error(data.detail || `Request failed (${response.status})`);
    }
    return data;
}

// ---------------- CITIZEN MAP ----------------

function initCitizenMap() {
    if (!$("map") || !window.L) return;

    citizenMap = L.map("map").setView(BLR, 12);

    L.tileLayer(
        "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
        { attribution: "© OpenStreetMap contributors" }
    ).addTo(citizenMap);

    citizenMap.on("click", e =>
        setLocation(e.latlng.lat, e.latlng.lng, "map")
    );

    setTimeout(() => citizenMap.invalidateSize(), 250);
}

async function setLocation(lat, lon, source = "gps") {
    if (!$("latitude") || !$("longitude")) return;
    $("latitude").value = Number(lat).toFixed(7);
    $("longitude").value = Number(lon).toFixed(7);
    if ($("location_source")) $("location_source").value = source;

    if ($("coords")) $("coords").textContent =
        `Latitude ${lat.toFixed(5)} · Longitude ${lon.toFixed(5)}`;

    if ($("locationStatus")) $("locationStatus").textContent = "Identifying Bengaluru ward...";

    if (citizenMap) {
        citizenMap.setView([lat, lon], 16);

        if (citizenMarker) citizenMarker.setLatLng([lat, lon]);
        else citizenMarker = L.marker([lat, lon]).addTo(citizenMap);
    }

    try {
        const result = await api(
            `/api/geo/ward?latitude=${lat}&longitude=${lon}`
        );

        if ($("wardResult")) $("wardResult").textContent = result.matched
            ? `Ward: ${result.ward_name} · Corporation: ${result.corporation} · Zone: ${result.zone}`
            : result.reason;

    } catch (error) {
        if ($("wardResult")) $("wardResult").textContent =
            "Ward lookup unavailable. Coordinates are retained.";
    }

    if ($("locationStatus")) $("locationStatus").textContent = "Location selected.";

    // Reverse geocoding after explicit location selection.
    try {
        const response = await fetch(
            `https://nominatim.openstreetmap.org/reverse?format=jsonv2&lat=${lat}&lon=${lon}`
        );

        if (response.ok) {
            const result = await response.json();

            if (result.display_name && $("address") &&
                !$("address").value) {
                $("address").value = result.display_name;
            }
        }
    } catch (error) {
        console.warn("Reverse geocoding unavailable.");
    }
}

// ---------------- CITIZEN PORTAL ----------------

function initCitizen() {
    if (!$("complaintForm")) return;

    initCitizenMap();

    $("gpsBtn")?.addEventListener("click", () => {
        if (!navigator.geolocation) {
            $("locationStatus").textContent =
                "GPS is not supported by this browser.";
            return;
        }

        $("locationStatus").textContent = "Requesting GPS permission...";

        navigator.geolocation.getCurrentPosition(
            position => setLocation(
                position.coords.latitude,
                position.coords.longitude,
                "gps"
            ),
            error => {
                $("locationStatus").textContent =
                    `GPS unavailable: ${error.message}`;
            },
            {
                enableHighAccuracy: true,
                timeout: 15000,
                maximumAge: 30000
            }
        );
    });

    $("latitude")?.addEventListener("change", manualCoords);
    $("longitude")?.addEventListener("change", manualCoords);

    $("complaintForm").addEventListener("submit", async e => {
        e.preventDefault();

        const form = e.currentTarget instanceof HTMLFormElement
            ? e.currentTarget
            : $("complaintForm");
        if (!form) return;
        const button = e.submitter;
        if (button) { button.disabled = true; button.textContent = "Submitting..."; }

        try {
            const formData = new FormData(form);

            if (!formData.get("latitude") ||
                !formData.get("longitude")) {
                formData.delete("latitude");
                formData.delete("longitude");
            }

            const result = await api("/api/complaints", {
                method: "POST",
                body: formData
            });

            $("submitMessage").className = "form-message success";
            const dupBanner = result.is_duplicate
                ? `<div class="duplicate-alert-banner"><strong>👥 Community Alert:</strong> <strong>${result.complaints_count} citizens</strong> have reported this same issue in your area. Your report is linked to consolidated issue <strong>${escapeHtml(result.group_reference || "")}</strong>.</div>`
                : `<div class="duplicate-alert-banner">Issue registered. Associated with consolidated issue <strong>${escapeHtml(result.group_reference || "")}</strong>.</div>`;
            $("submitMessage").innerHTML = `Complaint saved. Reference: <strong>${escapeHtml(result.reference)}</strong>. <a href="/track?reference=${encodeURIComponent(result.reference)}">Track this complaint</a>.<br>${dupBanner}`;

            if (form.isConnected && typeof form.reset === "function") {
                form.reset();
            }

            if (citizenMarker) {
                citizenMap.removeLayer(citizenMarker);
                citizenMarker = null;
            }

            $("coords").textContent = "Latitude — · Longitude —";
            $("locationStatus").textContent = "No location selected yet.";

            await loadRecent();

        } catch (error) {
            $("submitMessage").className = "form-message error";
            $("submitMessage").textContent = error.message;
        } finally {
            if (button) { button.disabled = false; button.innerHTML = "Submit complaint <span>→</span>"; }
        }
    });

    $("askForm")?.addEventListener("submit", async e => {
        e.preventDefault();

        const box = $("answerBox");
        if (!box) return;
        box.classList.remove("hidden");
        box.textContent = "Searching indexed documents...";

        try {
            const question = new FormData(e.currentTarget).get("question");

            const result = await api("/api/ask", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ question })
            });

            box.textContent =
                result.answer + "\n\nSources:\n" +
                (result.sources || []).map(
                    s => `[${s.citation}] ${s.source} · ${s.path}${s.url ? ` · ${s.url}` : ""}`
                ).join("\n");

        } catch (error) {
            box.textContent = error.message;
        }
    });

    loadRecent();
}

function manualCoords() {
    const lat = parseFloat($("latitude").value);
    const lon = parseFloat($("longitude").value);

    if (Number.isFinite(lat) && Number.isFinite(lon)) {
        setLocation(lat, lon, "manual");
    }
}

async function loadRecent() {
    if (!$("recentList")) return;

    try {
        const rows = await api("/api/complaints");

        $("recentList").innerHTML = rows.slice(0, 4).map(x => `
            <div class="recent-item">
                <div>
                    <strong>${escapeHtml(x.title)}</strong>
                    <small>${escapeHtml(x.reference)}</small>
                </div>
                <span class="status-chip">${escapeHtml(x.status)}</span>
            </div>
        `).join("") || "No complaints submitted yet.";

    } catch (error) {
        $("recentList").textContent = `Could not load recent complaints: ${error.message}`;
    }
}

// ---------------- ADMIN DASHBOARD & PRIORITY COMMAND CENTER ----------------

let currentPriorityFilter = "";
let priorityMapMarkers = [];
let priorityHeatLayer = null;
let heatmapActive = false;
let priorityMapBounds = [];
let cachedPriorityQueue = [];

function initAdmin() {
    if (!$("kpiTotal") && !$("adminMap")) return;

    initAdminMap();
    initPriorityControls();

    $("refreshBtn")?.addEventListener("click", () => {
        refreshDashboard();
        loadPrioritySummary();
        loadPriorityMapPoints();
        loadPriorityQueue();
        loadTable();
    });

    $("ingestBtn")?.addEventListener("click", async () => {
        const button = $("ingestBtn");
        button.disabled = true;
        button.textContent = "Indexing...";

        try {
            const result = await api("/api/rag/ingest", {
                method: "POST"
            });

            alert(`Indexed ${result.documents} documents and ${result.chunks} chunks.`);
        } catch (error) {
            alert("Indexing failed: " + error.message);
        } finally {
            button.disabled = false;
            button.textContent = "Re-index knowledge base";
        }
    });

    $("tableSearch")?.addEventListener("input", loadTable);
    $("complaintRows")?.addEventListener("change", async e => {
        const select = e.target.closest("select[data-complaint-id]");
        if (!select) return;
        const remarks = window.prompt("Add an action note for this status update (optional):") || "";
        await updateComplaintStatus(select.dataset.complaintId, select.value, remarks);
    });

    $("reclusterBtn")?.addEventListener("click", async () => {
        const btn = $("reclusterBtn");
        btn.disabled = true;
        btn.textContent = "Clustering…";
        try {
            await api("/api/groups/recluster", { method: "POST" });
            await loadPrioritySummary();
            await loadPriorityMapPoints();
            await loadPriorityQueue();
            await loadTable();
        } catch (e) {
            alert("Re-clustering error: " + e.message);
        } finally {
            btn.disabled = false;
            btn.textContent = "↺ Re-cluster";
        }
    });

    $("modalCloseBtn")?.addEventListener("click", closeGroupModal);
    $("groupModal")?.addEventListener("click", e => {
        if (e.target.id === "groupModal") closeGroupModal();
    });

    $("groupStatusForm")?.addEventListener("submit", async e => {
        e.preventDefault();
        const gid = $("modalGroupId").value;
        const status = $("modalStatusSelect").value;
        const assigned_department = $("modalDepartmentInput").value.trim() || null;
        const assigned_officer = $("modalOfficerInput").value.trim() || null;
        const remarks = $("modalRemarksInput").value.trim() || null;
        const statusMsg = $("groupActionStatus");
        const saveBtn = $("saveGroupStatusBtn");

        saveBtn.disabled = true;
        saveBtn.textContent = "Updating & Notifying…";
        statusMsg.className = "form-action-msg";
        statusMsg.textContent = "";

        try {
            const updated = await api(`/api/groups/${gid}/status`, {
                method: "PATCH",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ status, remarks, assigned_department, assigned_officer })
            });
            statusMsg.className = "form-action-msg success";
            statusMsg.textContent = `✓ Status updated to ${status}. ${updated.complaints_count} citizens notified!`;
            await openGroupDetails(gid);
            await loadPrioritySummary();
            await loadPriorityMapPoints();
            await loadPriorityQueue();
            await loadTable();
        } catch (err) {
            statusMsg.className = "form-action-msg error";
            statusMsg.textContent = `Error: ${err.message}`;
        } finally {
            saveBtn.disabled = false;
            saveBtn.innerHTML = "Update Status & Notify Citizens <span>→</span>";
        }
    });

    // Priority manual override
    $("savePriorityOverrideBtn")?.addEventListener("click", async () => {
        const gid = $("modalGroupId").value;
        const priority = $("modalPriorityOverrideSelect").value;
        const reason = $("modalPriorityReasonInput").value.trim() || `Manual override to ${priority} by administrator`;
        const statusMsg = $("priorityOverrideStatus");
        const btn = $("savePriorityOverrideBtn");

        btn.disabled = true;
        statusMsg.className = "form-action-msg";
        statusMsg.textContent = "Updating priority...";

        try {
            await api(`/api/groups/${gid}/priority`, {
                method: "PATCH",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ priority, reason, overridden_by: "Administrator" })
            });
            statusMsg.className = "form-action-msg success";
            statusMsg.textContent = `✓ Priority updated to ${priority}!`;
            await openGroupDetails(gid);
            await loadPrioritySummary();
            await loadPriorityMapPoints();
            await loadPriorityQueue();
        } catch (err) {
            statusMsg.className = "form-action-msg error";
            statusMsg.textContent = `Override failed: ${err.message}`;
        } finally {
            btn.disabled = false;
        }
    });

    refreshDashboard();
    loadPrioritySummary();
    loadPriorityMapPoints();
    loadPriorityQueue();
    loadTable();
    loadDatasets();
}

function initPriorityControls() {
    // View Switchers: Queue Table vs Cards
    $("viewQueueTableBtn")?.addEventListener("click", () => {
        $("viewQueueTableBtn")?.classList.add("active");
        $("viewQueueCardsBtn")?.classList.remove("active");
        $("queueTableView")?.classList.remove("hidden");
        $("queueCardsView")?.classList.add("hidden");
    });

    $("viewQueueCardsBtn")?.addEventListener("click", () => {
        $("viewQueueCardsBtn")?.classList.add("active");
        $("viewQueueTableBtn")?.classList.remove("active");
        $("queueTableView")?.classList.add("hidden");
        $("queueCardsView")?.classList.remove("hidden");
    });

    // Map control buttons
    $("toggleHeatmapBtn")?.addEventListener("click", window.toggleHeatmap);
    $("focusCriticalBtn")?.addEventListener("click", window.focusCriticalIssues);
    $("resetMapBtn")?.addEventListener("click", window.resetMap);

    // Filter controls
    $("mapCategoryFilter")?.addEventListener("change", () => {
        loadPriorityMapPoints();
        loadPriorityQueue();
    });

    $("mapStatusFilter")?.addEventListener("change", () => {
        loadPriorityMapPoints();
        loadPriorityQueue();
    });

    let searchTimer = null;
    $("mapSearchInput")?.addEventListener("input", () => {
        clearTimeout(searchTimer);
        searchTimer = setTimeout(() => {
            loadPriorityMapPoints();
            loadPriorityQueue();
        }, 250);
    });
}

async function loadPrioritySummary() {
    try {
        const summary = await api("/api/priority/summary");

        const crit = summary.critical || 0;
        const high = summary.high || 0;
        const med = summary.medium || 0;
        const low = summary.low || 0;
        const total = summary.total_unresolved || (crit + high + med + low);

        if ($("countCritical")) $("countCritical").textContent = crit;
        if ($("countHigh")) $("countHigh").textContent = high;
        if ($("countMedium")) $("countMedium").textContent = med;
        if ($("countLow")) $("countLow").textContent = low;

        const maxVal = Math.max(1, total);
        if ($("barCritical")) $("barCritical").style.width = `${Math.min(100, Math.round((crit / maxVal) * 100))}%`;
        if ($("barHigh")) $("barHigh").style.width = `${Math.min(100, Math.round((high / maxVal) * 100))}%`;
        if ($("barMedium")) $("barMedium").style.width = `${Math.min(100, Math.round((med / maxVal) * 100))}%`;
        if ($("barLow")) $("barLow").style.width = `${Math.min(100, Math.round((low / maxVal) * 100))}%`;

        if ($("pillCountAll")) $("pillCountAll").textContent = total;
        if ($("pillCountCritical")) $("pillCountCritical").textContent = crit;
        if ($("pillCountHigh")) $("pillCountHigh").textContent = high;
        if ($("pillCountMedium")) $("pillCountMedium").textContent = med;
        if ($("pillCountLow")) $("pillCountLow").textContent = low;

        if ($("clusterSummaryPill")) {
            $("clusterSummaryPill").textContent = `${summary.total_groups || total} Consolidated Issues · ${summary.total_citizens || 0} Citizens Reporting · ${crit} Critical Hazards`;
        }

        if ($("kpiGroups")) $("kpiGroups").textContent = (summary.total_groups || 0).toLocaleString("en-IN");
        if ($("kpiGroupsSub")) $("kpiGroupsSub").textContent = `${summary.total_citizens || 0} citizens reporting`;
    } catch (e) {
        console.warn("Could not load priority summary:", e);
    }
}

function getPrioritySymbol(tier) {
    switch (tier) {
        case "Critical": return "!";
        case "High": return "▲";
        case "Medium": return "●";
        case "Low": return "▼";
        default: return "●";
    }
}

async function loadPriorityMapPoints() {
    if (!adminMap) return;

    const cat = $("mapCategoryFilter")?.value || "";
    const stat = $("mapStatusFilter")?.value ?? "Unresolved";
    const search = ($("mapSearchInput")?.value || "").trim();

    const params = new URLSearchParams();
    if (currentPriorityFilter) params.set("priority", currentPriorityFilter);
    if (cat) params.set("category", cat);
    if (stat) params.set("status", stat);
    if (search) params.set("search", search);

    try {
        const data = await api(`/api/priority/map-points?${params.toString()}`);
        const points = data.points || [];

        // Clear existing markers
        priorityMapMarkers.forEach(m => adminMap.removeLayer(m));
        priorityMapMarkers = [];

        // Clear heatmap
        if (priorityHeatLayer && adminMap.hasLayer(priorityHeatLayer)) {
            adminMap.removeLayer(priorityHeatLayer);
            priorityHeatLayer = null;
        }

        // Render Heatmap Layer if active
        if (heatmapActive && window.L && typeof L.heatLayer === "function") {
            const heatData = points
                .filter(p => Number.isFinite(p.latitude) && Number.isFinite(p.longitude))
                .map(p => [p.latitude, p.longitude, Math.max(0.4, (p.priority_score || 50) / 100)]);
            if (heatData.length) {
                priorityHeatLayer = L.heatLayer(heatData, {
                    radius: 32,
                    blur: 22,
                    maxZoom: 16,
                    gradient: { 0.2: '#16a34a', 0.5: '#ca8a04', 0.75: '#ea580c', 1.0: '#dc2626' }
                }).addTo(adminMap);
            }
        }

        priorityMapBounds = [];

        // Render Markers
        points.forEach(p => {
            if (!Number.isFinite(p.latitude) || !Number.isFinite(p.longitude)) return;

            const pClass = (p.priority || "Medium").toLowerCase();
            const citizenCount = p.complaints_count || 1;
            const citizenBadge = citizenCount > 1 ? `<span class="marker-citizen-badge">👥 ${citizenCount}</span>` : "";

            const icon = L.divIcon({
                className: `priority-map-marker marker-${pClass}`,
                html: `<div class="marker-pin"><span class="marker-inner-icon">${getPrioritySymbol(p.priority)}</span></div>${citizenBadge}`,
                iconSize: [34, 34],
                iconAnchor: [17, 34],
                popupAnchor: [0, -32]
            });

            const marker = L.marker([p.latitude, p.longitude], { icon }).addTo(adminMap);

            const popupContent = `
                <div class="map-popup-card">
                    <div class="popup-top-row">
                        <span class="popup-ref">${escapeHtml(p.reference || ('GRP-' + p.group_id))}</span>
                        <span class="priority-badge priority-badge-${pClass}">
                            ${pClass === 'critical' ? '🔴' : pClass === 'high' ? '🟠' : pClass === 'medium' ? '🟡' : '🟢'} ${escapeHtml(p.priority)} · ${p.priority_score}
                        </span>
                    </div>
                    <h4 class="popup-title">${escapeHtml(p.title)}</h4>
                    <p class="popup-summary">${escapeHtml(p.summary || '')}</p>
                    <div class="popup-meta-grid">
                        <div><span>CATEGORY</span><strong>${escapeHtml(p.category || 'General')}</strong></div>
                        <div><span>LOCATION</span><strong>${escapeHtml(p.ward_name || p.address || 'Bengaluru')}</strong></div>
                        <div><span>AFFECTED</span><strong>👥 ${citizenCount} citizens</strong></div>
                        <div><span>DAYS OPEN</span><strong>${p.days_unresolved ?? 0} days</strong></div>
                        <div><span>FIRST REPORT</span><strong>${formatDateShort(p.first_reported_at)}</strong></div>
                        <div><span>STATUS</span><strong>${escapeHtml(p.status || 'Submitted')}</strong></div>
                    </div>
                    <button class="popup-btn" type="button" onclick="openGroupDetails(${Number(p.group_id)})">Manage Issue →</button>
                </div>
            `;

            marker.bindPopup(popupContent, { maxWidth: 320 });
            priorityMapMarkers.push(marker);
            priorityMapBounds.push([p.latitude, p.longitude]);
        });

        if ($("mapStatusPill")) {
            $("mapStatusPill").textContent = `${points.length} Incidents Mapped`;
        }

    } catch (e) {
        console.error("Failed to load priority map points:", e);
    }
}

async function loadPriorityQueue() {
    const cat = $("mapCategoryFilter")?.value || "";
    const stat = $("mapStatusFilter")?.value ?? "Unresolved";
    const search = ($("mapSearchInput")?.value || "").trim();

    const params = new URLSearchParams();
    if (currentPriorityFilter) params.set("priority", currentPriorityFilter);
    if (cat) params.set("category", cat);
    if (stat) params.set("status", stat);
    if (search) params.set("search", search);

    try {
        const data = await api(`/api/priority/queue?${params.toString()}`);
        cachedPriorityQueue = data.queue || [];
        renderPriorityQueueTable(cachedPriorityQueue);
        renderPriorityQueueCards(cachedPriorityQueue);
    } catch (e) {
        if ($("priorityQueueRows")) {
            $("priorityQueueRows").innerHTML = `<tr><td colspan="9" class="empty-state">Could not load priority queue: ${escapeHtml(e.message)}</td></tr>`;
        }
    }
}

function renderPriorityQueueTable(items) {
    const tbody = $("priorityQueueRows");
    if (!tbody) return;

    if (!items.length) {
        tbody.innerHTML = `<tr><td colspan="9" class="empty-state">No civic issues match the active priority/filter criteria.</td></tr>`;
        return;
    }

    tbody.innerHTML = items.map(g => {
        const pClass = (g.priority || "Medium").toLowerCase();
        const citizenCount = g.complaints_count || 1;
        const isMulti = citizenCount > 1;
        const dupBadge = isMulti
            ? `<span class="duplicate-pill high-impact">👥 ${citizenCount} reports</span>`
            : `<span class="duplicate-pill">👤 1 report</span>`;
        const locationText = [g.ward_name, g.address].filter(Boolean).join(" · ") || "Not provided";
        const isOverdue = (g.days_unresolved || 0) > 7;

        return `
            <tr>
                <td>
                    <span class="priority-badge priority-badge-${pClass}">
                        ${pClass === 'critical' ? '🔴' : pClass === 'high' ? '🟠' : pClass === 'medium' ? '🟡' : '🟢'} ${escapeHtml(g.priority)} · ${g.priority_score}
                    </span>
                </td>
                <td><strong>${escapeHtml(g.reference)}</strong></td>
                <td class="queue-title-cell">
                    <strong>${escapeHtml(g.title)}</strong>
                    <small title="${escapeAttribute(g.summary)}">${escapeHtml(g.summary)}</small>
                </td>
                <td>${escapeHtml(g.category)}</td>
                <td>${escapeHtml(locationText)}</td>
                <td>${dupBadge}</td>
                <td>
                    <span class="days-open-badge ${isOverdue ? 'overdue' : ''}">
                        ${isOverdue ? '⚠️ ' : ''}${g.days_unresolved ?? 0}d
                    </span>
                </td>
                <td><span class="status-chip">${escapeHtml(g.status)}</span></td>
                <td>
                    <button class="manage-link-btn" onclick="openGroupDetails(${Number(g.id)})" type="button">Manage ↗</button>
                </td>
            </tr>
        `;
    }).join("");
}

function renderPriorityQueueCards(items) {
    const container = $("queueCardsView");
    if (!container) return;

    if (!items.length) {
        container.innerHTML = `<div class="empty-state">No matching consolidated issues found.</div>`;
        return;
    }

    container.innerHTML = items.map(g => {
        const pClass = (g.priority || "Medium").toLowerCase();
        const citizenCount = g.complaints_count || 1;
        const isMulti = citizenCount > 1;
        const dupBadge = isMulti
            ? `<span class="duplicate-pill high-impact">👥 ${citizenCount} citizens reported</span>`
            : `<span class="duplicate-pill">👤 1 citizen reported</span>`;
        const locationText = [g.ward_name, g.address].filter(Boolean).join(" · ") || "Location not provided";
        const isOverdue = (g.days_unresolved || 0) > 7;

        return `
            <article class="consolidated-card" onclick="openGroupDetails(${Number(g.id)})" style="border-top: 3px solid ${pClass === 'critical' ? '#dc2626' : pClass === 'high' ? '#ea580c' : pClass === 'medium' ? '#ca8a04' : '#16a34a'}">
                <div>
                    <div class="card-top-meta">
                        <span class="card-group-ref">${escapeHtml(g.reference)}</span>
                        <span class="priority-badge priority-badge-${pClass}">
                            ${pClass === 'critical' ? '🔴' : pClass === 'high' ? '🟠' : pClass === 'medium' ? '🟡' : '🟢'} ${escapeHtml(g.priority)} · ${g.priority_score}
                        </span>
                    </div>
                    <h4>${escapeHtml(g.title)}</h4>
                    <p class="card-summary">${escapeHtml(g.summary)}</p>
                    <div class="card-details-grid">
                        <div class="card-detail-item">
                            <span>CATEGORY</span>
                            <strong>${escapeHtml(g.category)}</strong>
                        </div>
                        <div class="card-detail-item">
                            <span>LOCATION / WARD</span>
                            <strong>${escapeHtml(locationText)}</strong>
                        </div>
                        <div class="card-detail-item">
                            <span>AFFECTED CITIZENS</span>
                            <strong>${dupBadge}</strong>
                        </div>
                        <div class="card-detail-item">
                            <span>DAYS UNRESOLVED</span>
                            <strong class="${isOverdue ? 'error' : ''}">${g.days_unresolved ?? 0} days open</strong>
                        </div>
                    </div>
                </div>
                <div class="card-footer-row">
                    <span class="status-chip">${escapeHtml(g.status)}</span>
                    <button class="manage-link-btn" type="button">Manage issue →</button>
                </div>
            </article>
        `;
    }).join("");
}

window.setPriorityFilter = function(tier) {
    currentPriorityFilter = tier || "";

    const tabs = {
        "": "tabAll",
        "Critical": "tabCritical",
        "High": "tabHigh",
        "Medium": "tabMedium",
        "Low": "tabLow"
    };
    Object.entries(tabs).forEach(([k, id]) => {
        if ($(id)) {
            if (k === currentPriorityFilter) $(id).classList.add("active");
            else $(id).classList.remove("active");
        }
    });

    const cards = {
        "Critical": "cardFilterCritical",
        "High": "cardFilterHigh",
        "Medium": "cardFilterMedium",
        "Low": "cardFilterLow"
    };
    Object.entries(cards).forEach(([k, id]) => {
        if ($(id)) {
            if (k === currentPriorityFilter) $(id).classList.add("active");
            else $(id).classList.remove("active");
        }
    });

    loadPriorityMapPoints();
    loadPriorityQueue();
};

window.togglePriorityFilter = function(tier) {
    if (currentPriorityFilter === tier) {
        window.setPriorityFilter("");
    } else {
        window.setPriorityFilter(tier);
    }
};

window.toggleHeatmap = function() {
    heatmapActive = !heatmapActive;
    const btn = $("toggleHeatmapBtn");
    if (btn) {
        if (heatmapActive) {
            btn.classList.add("active");
            btn.style.background = "#eaf5ee";
            btn.style.borderColor = "#1c6b4b";
        } else {
            btn.classList.remove("active");
            btn.style.background = "";
            btn.style.borderColor = "";
        }
    }
    loadPriorityMapPoints();
};

window.focusCriticalIssues = function() {
    window.setPriorityFilter("Critical");
    setTimeout(() => {
        if (priorityMapBounds.length > 0 && adminMap) {
            if (priorityMapBounds.length === 1) {
                adminMap.setView(priorityMapBounds[0], 16);
            } else {
                adminMap.fitBounds(priorityMapBounds, { padding: [50, 50], maxZoom: 16 });
            }
        }
    }, 300);
};

window.resetMap = function() {
    if (!adminMap) return;
    if (priorityMapBounds.length > 0) {
        adminMap.fitBounds(priorityMapBounds, { padding: [30, 30], maxZoom: 14 });
    } else {
        adminMap.setView(BLR, 12);
    }
};

async function refreshDashboard() {
    let result = null;
    try {
        result = await api("/api/dashboard/historical");
    } catch (err) {
        console.warn("Historical analytics unavailable, trying live complaints dashboard:", err);
    }

    if (!result || !result.kpis) {
        try {
            result = await api("/api/dashboard");
        } catch (err2) {
            console.warn("Dashboard live analytics error, falling back to local calculation:", err2);
        }
    }

    if (!result || !result.kpis) {
        try {
            const complaints = await api("/api/complaints");
            const total = complaints.length;
            const open = complaints.filter(c => c.status !== "Resolved" && c.status !== "Rejected").length;
            const resolved = complaints.filter(c => c.status === "Resolved").length;
            const gps = complaints.filter(c => c.latitude && c.longitude).length;
            const catMap = {};
            const statMap = {};
            complaints.forEach(c => {
                catMap[c.category] = (catMap[c.category] || 0) + 1;
                statMap[c.status] = (statMap[c.status] || 0) + 1;
            });
            result = {
                data_type: "live",
                kpis: {
                    total_complaints: total,
                    open_complaints: open,
                    resolved_complaints: resolved,
                    resolution_rate_percent: total ? Math.round((resolved / total) * 100) : 0,
                    records_with_gps: gps
                },
                categories: Object.entries(catMap).map(([category, count]) => ({ category, complaints: count })),
                statuses: Object.entries(statMap).map(([status, count]) => ({ status, complaints: count })),
                monthly: []
            };
        } catch (err3) {
            console.error("Dashboard calculation failed completely:", err3);
        }
    }

    if (!result || !result.kpis) {
        ["kpiTotal", "kpiOpen", "kpiResolved", "kpiRate", "kpiMonth", "kpiGeo"].forEach(id => {
            if ($(id)) $(id).textContent = "—";
        });
        const notice = $("demoNotice");
        notice?.remove();
        return;
    }

    const k = result.kpis;
    if ($("kpiTotal")) $("kpiTotal").textContent = (k.total_complaints ?? 0).toLocaleString("en-IN");
    if ($("kpiOpen")) $("kpiOpen").textContent = (k.open_complaints ?? 0).toLocaleString("en-IN");
    if ($("kpiResolved")) $("kpiResolved").textContent = (k.resolved_complaints ?? 0).toLocaleString("en-IN");
    if ($("kpiRate")) $("kpiRate").textContent = (k.resolution_rate_percent ?? 0) + "%";
    if ($("kpiMonth")) $("kpiMonth").textContent = result.data_type === "historical" ? "2019–2022" : "Live data";
    if ($("kpiGeo")) $("kpiGeo").textContent = (k.records_with_gps ?? 0).toLocaleString("en-IN");

    const notice = $("demoNotice");
    if (result.demo_notice) {
        notice?.classList.remove("hidden");
    } else {
        notice?.remove();
    }

    // Safely render category chart
    const categories = result.categories || [];
    drawChart(
        "categoryChart",
        "bar",
        categories.slice(0, 10).map(x => x.category),
        categories.slice(0, 10).map(x => x.complaints),
        result.data_type === "historical" ? "Historical complaints" : "Live complaints"
    );

    // Safely render status chart
    const statuses = result.statuses || [];
    drawChart(
        "statusChart",
        "doughnut",
        statuses.map(x => x.status),
        statuses.map(x => x.complaints),
        "Status Distribution"
    );

    // Safely render monthly / trend chart
    const monthly = result.monthly || [];
    const yearly = new Map();
    monthly.forEach(x => {
        const year = String(x.month || "").slice(0, 4);
        if (year) yearly.set(year, (yearly.get(year) || 0) + (x.complaints || 0));
    });

    let years = Array.from(yearly.keys()).sort();
    if (!years.length) {
        years = Array.from({ length: 8 }, (_, i) => String(2019 + i));
    }
    drawChart(
        "monthlyChart",
        "line",
        years,
        years.map(year => yearly.get(year) || 0),
        result.data_type === "historical" ? "Complaints by year" : "Complaints trend"
    );

    try {
        await loadMapLayers();
    } catch (e) {
        console.warn("Map layers error:", e);
    }
}

// ---------------- CHARTS ----------------

function drawChart(id, type, labels, values, seriesLabel = "Historical complaints") {
    const canvas = $(id);

    if (!canvas || !window.Chart) return;

    if (charts[id]) charts[id].destroy();

    charts[id] = new Chart(canvas, {
        type,
        data: {
            labels,
            datasets: [{
                label: seriesLabel,
                data: values,
                backgroundColor: type === "line"
                    ? "rgba(40,116,81,0.15)"
                    : [
                        "#287451", "#5A9B78", "#91BBA1",
                        "#C4DCCB", "#D8A56A", "#8397BD",
                        "#B5A5C9", "#D28D87", "#87AEB4",
                        "#B7AA91"
                    ],
                borderColor: "#287451",
                borderWidth: 2,
                fill: type === "line",
                tension: 0.35
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            indexAxis: type === "bar" ? "y" : "x",
            plugins: {
                legend: {
                    display: type === "doughnut",
                    position: "bottom"
                }
            },
            scales: type === "doughnut" ? {} : {
                x: { grid: { display: false }, ...(id === "monthlyChart" ? { title: { display: true, text: "Year" } } : {}) },
                y: { beginAtZero: true }
            }
        }
    });
}

// ---------------- COMPLAINT REGISTER ----------------

async function loadTable() {
    if (!$("complaintRows")) return;

    const query = ($("tableSearch")?.value || "").toLowerCase();

    try {
        const rows = await api("/api/complaints");

        const filtered = rows.filter(x =>
            [
                x.reference, x.title, x.category,
                x.address, x.ward_name
            ].join(" ").toLowerCase().includes(query)
        );

        $("complaintRows").innerHTML = filtered.map(x => `
            <tr>
                <td><strong>${escapeHtml(x.reference)}</strong></td>
                <td>${escapeHtml(x.title)}</td>
                <td>${escapeHtml(x.category)}</td>
                <td>
                    ${x.group_id ? `<button class="manage-link-btn" onclick="openGroupDetails(${Number(x.group_id)})" type="button" title="View consolidated issue">GRP-${Number(x.group_id)} ↗</button>` : `<span class="muted">—</span>`}
                </td>
                <td>${escapeHtml(x.ward_name || x.address || "Not provided")}</td>
                <td>${new Date(x.created_at).toLocaleDateString()}</td>
                <td><span class="status-chip">${escapeHtml(x.status)}</span></td>
                <td>
                    <select data-complaint-id="${Number(x.id)}">
                        ${["Submitted","Under Review","In Progress","Resolved","Rejected"].map(s =>
                            `<option value="${s}" ${x.status === s ? "selected" : ""}>${s}</option>`
                        ).join("")}
                    </select>
                </td>
            </tr>
        `).join("") || `
            <tr><td colspan="8" class="empty-state">No matching complaints.</td></tr>
        `;

    } catch (error) {
        $("complaintRows").innerHTML =
            `<tr><td colspan="8">Could not load live complaints: ${escapeHtml(error.message)}</td></tr>`;
    }
}

window.updateComplaintStatus = async (id, status, remarks = "") => {
    try {
        await api(`/api/complaints/${id}/status`, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ status, remarks })
        });

        await loadTable();
    } catch (error) {
        await loadTable();
        const rows = $("complaintRows");
        if (rows) {
            const message = document.createElement("tr");
            const cell = document.createElement("td");
            cell.colSpan = 7;
            cell.className = "error";
            cell.textContent = `Status update failed: ${error.message}`;
            message.appendChild(cell);
            rows.prepend(message);
        }
    }
};

// ---------------- BENGALURU MAP ----------------

function initAdminMap() {
    if (!$("adminMap") || !window.L) return;

    adminMap = L.map("adminMap").setView(BLR, 11);

    L.tileLayer(
        "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
        { attribution: "© OpenStreetMap contributors" }
    ).addTo(adminMap);

    setTimeout(() => adminMap.invalidateSize(), 250);
}

async function loadMapLayers() {
    if (!adminMap) return;

    try {
        // Remove old layers before refreshing.
        [wardLayer, historicalLayer, liveLayer].forEach(layer => {
            if (layer && adminMap.hasLayer(layer)) {
                adminMap.removeLayer(layer);
            }
        });

        // Load the 369 GBA ward polygons as subtle background context.
        const wards = await api("/api/geo/wards");

        wardLayer = L.geoJSON(wards, {
            style: {
                color: "#287451",
                weight: 0.8,
                fillColor: "#8ab69a",
                fillOpacity: 0.04
            },
            onEachFeature: (feature, layer) => {
                const p = feature.properties || {};

                layer.bindPopup(`
                    <strong>${escapeHtml(p.ward_name)}</strong><br>
                    Corporation: ${escapeHtml(p.Corporation)}<br>
                    Ward ID: ${escapeHtml(p.ward_id)}<br>
                    Zone: ${escapeHtml(p.zone_name)}
                `);
            }
        }).addTo(adminMap);

    } catch (error) {
        console.warn("Ward boundaries error:", error);
    }
}

// ---------------- DATASET INVENTORY ----------------

async function loadDatasets() {
    if (!$("datasetList")) return;

    try {
        const data = await api("/api/datasets");
        const files = (data.files || []).filter(file => file.file !== ".gitkeep");
        const sources = (data.sources?.datasets || []).filter(source =>
            String(source.status || "").trim().toLowerCase() !== "failed"
        );

        $("datasetList").innerHTML =
            files.map(file => `
                <div class="dataset-row">
                    <div>
                        <strong>${escapeHtml(file.file)}</strong>
                        <small>${file.size_kb} KB · ${escapeHtml((file.columns || []).slice(0,4).join(", "))}</small>
                    </div>
                    <span class="dataset-type">${escapeHtml(file.type)}</span>
                </div>
            `).join("") +
            sources.map(source => `
                <div class="dataset-row">
                    <div>
                        <strong>${escapeHtml(source.title || source.query || "Dataset")}</strong>
                        <small>${escapeHtml(source.status || "catalogued")}</small>
                    </div>
                </div>
            `).join("");

    } catch (error) {
        $("datasetList").textContent =
            "Dataset inventory unavailable.";
    }
}

// ---------------- STARTUP ----------------

document.addEventListener("DOMContentLoaded", () => {
    initCitizen();
    initAdmin();
    initTracking();
    if (typeof closeLightbox === "function") closeLightbox();
});

const TRACK_STAGES = [
    { status: "Submitted", title: "Complaint Submitted", detail: "Your complaint was registered in CivicResolve." },
    { status: "Under Review", title: "Under Review", detail: "The complaint is being verified." },
    { status: "Assigned to Department", title: "Assigned to Department", detail: "This stage will be shown when an assignment is recorded." },
    { status: "In Progress", title: "Work in Progress", detail: "Work on the reported issue is in progress." },
    { status: "Resolved", title: "Resolved", detail: "The complaint has been marked resolved." }
];

function initTracking() {
    const form = $("trackingForm");
    if (!form) return;
    const reference = new URLSearchParams(location.search).get("reference");
    if (reference) {
        $("trackingReference").value = reference;
        lookupTrackedComplaint(reference);
    }
    form.addEventListener("submit", async event => {
        event.preventDefault();
        await lookupTrackedComplaint($("trackingReference").value.trim());
    });
}

async function lookupTrackedComplaint(reference) {
    const message = $("trackingMessage");
    const result = $("trackingResult");
    const button = $("trackingButton");
    if (!reference) {
        message.className = "tracking-message error";
        message.textContent = "Enter a complaint reference number to continue.";
        result.classList.add("hidden");
        return;
    }
    button.disabled = true;
    button.textContent = "Looking up…";
    message.className = "tracking-message";
    message.textContent = "Searching for your complaint…";
    result.classList.add("hidden");
    try {
        const complaint = await api(`/api/complaints/track/${encodeURIComponent(reference)}`);
        renderTrackedComplaint(complaint);
        message.textContent = "Complaint details loaded.";
        result.classList.remove("hidden");
    } catch (error) {
        message.className = "tracking-message error";
        message.textContent = error.message.includes("404") || error.message.toLowerCase().includes("no complaint")
            ? "We couldn’t find a complaint with that reference. Check the number and try again."
            : `Could not load tracking details: ${error.message}`;
    } finally {
        button.disabled = false;
        button.innerHTML = 'Track complaint <span aria-hidden="true">→</span>';
    }
}

function renderTrackedComplaint(c) {
    const history = c.status_history || [];
    const current = c.status;
    const known = TRACK_STAGES.map(s => s.status);
    let activeIndex = known.indexOf(current);
    if (activeIndex < 0 && current === "Rejected") activeIndex = Math.max(0, known.indexOf(history.at(-1)?.previous_status));
    const eventsFor = status => history.filter(event => event.new_status === status);
    const location = [c.address, c.ward_name, c.corporation].filter(Boolean).join(" · ") || "Location not provided";
    const latest = history.at(-1);
    const progress = current === "Rejected" ? 0 : Math.max(0, activeIndex) / (TRACK_STAGES.length - 1) * 100;
    const stages = TRACK_STAGES.map((stage, index) => {
        const event = eventsFor(stage.status).at(-1);
        const wasRecorded = Boolean(event);
        const isCompleted = wasRecorded && (index < activeIndex || (index === activeIndex && current === "Resolved"));
        const isCurrent = index === activeIndex && current !== "Resolved" && current !== "Rejected";
        const state = isCompleted ? "completed" : isCurrent ? "current" : "pending";
        const icon = isCompleted ? "✓" : isCurrent ? "●" : "○";
        return `<li class="timeline-stage ${state}"><span class="timeline-icon" aria-label="${state}">${icon}</span><div class="timeline-copy"><div class="timeline-title">${escapeHtml(stage.title)}${isCurrent ? '<span class="stage-current-label">CURRENT</span>' : ""}</div><p>${escapeHtml(stage.detail)}</p>${event ? `<small>${formatDate(event.created_at)}${event.updated_by ? ` · ${escapeHtml(event.updated_by)}` : ""}</small>` : ""}${event?.remarks ? `<div class="timeline-note">${escapeHtml(event.remarks)}</div>` : ""}</div></li>`;
    }).join("");
    const statusLabel = current === "In Progress" ? "Work in Progress" : current;
    const image = c.resolution_image_path || c.resolution_photo_path;

    const groupSection = c.group ? `
      <section class="panel group-consolidation-badge">
        <div class="group-badge-head">
          <span class="badge-tag">CONSOLIDATED CIVIC ISSUE</span>
          <span class="citizen-count-chip">👥 ${c.group.complaints_count} citizens reported this</span>
        </div>
        <h4>${escapeHtml(c.group.title)}</h4>
        <p>${escapeHtml(c.group.summary)}</p>
        <div class="group-meta-row">
          <span>Consolidated Issue ID: <strong>${escapeHtml(c.group.reference)}</strong></span>
          <span>First reported: <strong>${formatDate(c.group.first_reported_at)}</strong></span>
          <span>Latest report: <strong>${formatDate(c.group.last_reported_at)}</strong></span>
          <span>Group status: <strong>${escapeHtml(c.group.status)}</strong></span>
        </div>
      </section>
    ` : "";

    const notifsSection = (c.notifications && c.notifications.length) ? `
      <section class="panel tracking-notifications">
        <div class="panel-head">
          <div>
            <span class="step">NOTIFICATIONS</span>
            <h3>Citizen Resolution Updates</h3>
          </div>
        </div>
        <div class="notifications-history-list">
          ${c.notifications.map(n => `
            <div class="notification-item ${escapeHtml(n.notification_type)}">
              <span class="notif-badge">${n.notification_type === 'issue_resolved' ? '✓ RESOLVED' : 'ℹ UPDATE'}</span>
              <div>
                <strong>${escapeHtml(n.title)}</strong>
                <p>${escapeHtml(n.message)}</p>
                <small>${formatDate(n.sent_at)} · Delivered to citizen</small>
              </div>
            </div>
          `).join("")}
        </div>
      </section>
    ` : "";

    $("trackingResult").innerHTML = `
      ${groupSection}
      <section class="tracking-latest panel"><div><span class="step">LATEST UPDATE</span><h2>${escapeHtml(statusLabel)}</h2><p>${latest?.remarks ? escapeHtml(latest.remarks) : "No additional action note has been recorded."}</p>${latest ? `<small>Updated ${formatDate(latest.created_at)}${latest.updated_by ? ` · ${escapeHtml(latest.updated_by)}` : ""}</small>` : ""}</div><span class="status-chip">${escapeHtml(statusLabel)}</span></section>
      <section class="panel tracking-details"><div class="panel-head"><div><span class="step">COMPLAINT DETAILS</span><h3>${escapeHtml(c.title)}</h3></div><span class="status-chip">${escapeHtml(statusLabel)}</span></div>
        <p class="tracking-description">${escapeHtml(c.description)}</p><div class="tracking-facts">
          ${trackingFact("Complaint ID", c.reference)}${trackingFact("Category", c.category)}${trackingFact("Location / Ward", location)}${trackingFact("Date submitted", formatDate(c.created_at))}${trackingFact("Last updated", formatDate(c.updated_at))}${trackingFact("Assigned department / officer", c.assigned_department || c.assigned_officer || "Not recorded")}
        </div>
      </section>
      <section class="panel tracking-progress"><div class="panel-head"><div><span class="step">PROGRESS</span><h3>What happens next</h3><p>Stages appear as updates are recorded for this complaint.</p></div><strong class="progress-percent">${Math.round(progress)}%</strong></div><div class="progress-track" role="progressbar" aria-label="Complaint progress" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${Math.round(progress)}"><span style="width:${progress}%"></span></div>${current === "Rejected" ? `<p class="tracking-rejected">This complaint was marked Rejected.${latest?.remarks ? ` ${escapeHtml(latest.remarks)}` : ""}</p>` : `<ol class="tracking-timeline">${stages}</ol>`}</section>
      <section class="panel tracking-resolution"><span class="step">RESOLUTION EVIDENCE</span><h3>Department remarks and photos</h3>${latest?.remarks ? `<p>${escapeHtml(latest.remarks)}</p>` : `<p>No department remarks have been recorded.</p>`}${image ? `<img class="resolution-photo" src="${escapeAttribute(image)}" alt="Complaint resolution evidence">` : `<p class="muted">No resolution photo is available.</p>`}</section>
      ${notifsSection}`;
}

function trackingFact(label, value) {
    return `<div class="tracking-fact"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value || "Not recorded")}</strong></div>`;
}

function formatDate(value) {
    if (!value) return "Not recorded";
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? "Not recorded" : date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}


// ---------------- CONSOLIDATED ISSUES (GROUPING & CLUSTERING) ----------------

let cachedGroups = [];
let modalGroupMap = null;
let modalMarkers = [];

async function loadConsolidatedGroups() {
    try {
        await loadPrioritySummary();
        await loadPriorityQueue();
        await loadPriorityMapPoints();

        const res = await api("/api/groups");
        cachedGroups = res.groups || [];

        // Update KPI card
        if ($("kpiGroups")) {
            $("kpiGroups").textContent = (res.total_groups || 0).toLocaleString("en-IN");
        }
        if ($("kpiGroupsSub")) {
            $("kpiGroupsSub").textContent = `${res.total_citizens || 0} citizens in ${res.multi_report_groups || 0} clusters`;
        }

        filterAndRenderConsolidated();
    } catch (e) {
        console.warn("Could not load consolidated groups:", e);
    }
}

function filterAndRenderConsolidated() {
    const search = ($("groupSearch")?.value || "").toLowerCase().trim();
    const cat = $("groupCategoryFilter")?.value || "";
    const stat = $("groupStatusFilter")?.value || "";

    const filtered = cachedGroups.filter(g => {
        if (cat && g.category !== cat) return false;
        if (stat && g.status !== stat) return false;
        if (search) {
            const haystack = [g.reference, g.title, g.summary, g.category, g.ward_name, g.address].join(" ").toLowerCase();
            if (!haystack.includes(search)) return false;
        }
        return true;
    });

    renderConsolidatedCards(filtered);
    renderConsolidatedTable(filtered);
}

function renderConsolidatedCards(groups) {
    const container = $("consolidatedCards");
    if (!container) return;

    if (!groups.length) {
        container.innerHTML = `<div class="empty-state">No matching consolidated issues found.</div>`;
        return;
    }

    container.innerHTML = groups.map(g => {
        const citizenCount = g.complaints_count || 1;
        const isMulti = citizenCount > 1;
        const dupBadge = isMulti
            ? `<span class="duplicate-pill high-impact">👥 ${citizenCount} citizens reported</span>`
            : `<span class="duplicate-pill">👤 1 citizen reported</span>`;
        const locationText = [g.ward_name, g.address].filter(Boolean).join(" · ") || "Location not provided";

        return `
            <article class="consolidated-card" onclick="openGroupDetails(${Number(g.id)})">
                <div>
                    <div class="card-top-meta">
                        <span class="card-group-ref">${escapeHtml(g.reference)}</span>
                        ${dupBadge}
                    </div>
                    <h4>${escapeHtml(g.title)}</h4>
                    <p class="card-summary">${escapeHtml(g.summary)}</p>
                    <div class="card-details-grid">
                        <div class="card-detail-item">
                            <span>CATEGORY</span>
                            <strong>${escapeHtml(g.category)}</strong>
                        </div>
                        <div class="card-detail-item">
                            <span>LOCATION / WARD</span>
                            <strong>${escapeHtml(locationText)}</strong>
                        </div>
                        <div class="card-detail-item">
                            <span>FIRST REPORTED</span>
                            <strong>${formatDateShort(g.first_reported_at)}</strong>
                        </div>
                        <div class="card-detail-item">
                            <span>LAST REPORTED</span>
                            <strong>${formatDateShort(g.last_reported_at)}</strong>
                        </div>
                    </div>
                </div>
                <div class="card-footer-row">
                    <span class="status-chip">${escapeHtml(g.status)}</span>
                    <button class="manage-link-btn" type="button">Manage issue →</button>
                </div>
            </article>
        `;
    }).join("");
}

function renderConsolidatedTable(groups) {
    const tbody = $("consolidatedTableRows");
    if (!tbody) return;

    if (!groups.length) {
        tbody.innerHTML = `<tr><td colspan="8" class="empty-state">No matching consolidated issues.</td></tr>`;
        return;
    }

    tbody.innerHTML = groups.map(g => {
        const citizenCount = g.complaints_count || 1;
        const dupBadge = citizenCount > 1
            ? `<span class="duplicate-pill high-impact">👥 ${citizenCount} reports</span>`
            : `<span class="duplicate-pill">👤 1 report</span>`;
        const locationText = [g.ward_name, g.address].filter(Boolean).join(" · ") || "Not provided";

        return `
            <tr>
                <td><strong>${escapeHtml(g.reference)}</strong></td>
                <td>
                    <div class="table-issue-title">${escapeHtml(g.title)}</div>
                    <div class="table-issue-summary">${escapeHtml(g.summary)}</div>
                </td>
                <td>${escapeHtml(g.category)}</td>
                <td>${escapeHtml(locationText)}</td>
                <td>${dupBadge}</td>
                <td>
                    <small>1st: ${formatDateShort(g.first_reported_at)}</small><br>
                    <small>Latest: ${formatDateShort(g.last_reported_at)}</small>
                </td>
                <td><span class="status-chip">${escapeHtml(g.status)}</span></td>
                <td>
                    <button class="manage-link-btn" onclick="openGroupDetails(${Number(g.id)})" type="button">View Details ↗</button>
                </td>
            </tr>
        `;
    }).join("");
}

function formatDateShort(val) {
    if (!val) return "—";
    const d = new Date(val);
    if (isNaN(d.getTime())) return "—";
    return d.toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

window.openGroupDetails = async function(gid) {
    const modal = $("groupModal");
    if (!modal) return;
    modal.style.display = "flex";
    modal.classList.remove("hidden");
    $("groupActionStatus").textContent = "";

    try {
        const group = await api(`/api/groups/${gid}`);
        $("modalGroupId").value = group.id;
        $("modalGroupRef").textContent = group.reference;
        $("modalGroupCategory").textContent = group.category;
        $("modalGroupStatus").textContent = group.status;
        $("modalGroupStatus").className = `status-chip`;
        $("modalGroupTitle").textContent = group.title;
        $("modalCitizenCount").textContent = group.complaints_count || (group.complaints || []).length;
        $("modalGroupLocation").textContent = [group.ward_name, group.address, group.corporation].filter(Boolean).join(" · ") || "Bengaluru";
        $("modalFirstReported").textContent = formatDate(group.first_reported_at);
        $("modalLastReported").textContent = formatDate(group.last_reported_at);
        $("modalAssigned").textContent = [group.assigned_department, group.assigned_officer].filter(Boolean).join(" / ") || "Unassigned";
        $("modalGroupSummary").textContent = group.summary;

        // Form values
        $("modalStatusSelect").value = group.status;
        $("modalDepartmentInput").value = group.assigned_department || "";
        $("modalOfficerInput").value = group.assigned_officer || "";
        $("modalRemarksInput").value = "";

        // Priority inspection card & override
        const pClass = (group.priority || "Medium").toLowerCase();
        if ($("modalPriorityCard")) {
            $("modalPriorityCard").className = `modal-section-card priority-inspection-card tier-${pClass}`;
        }
        if ($("modalPriorityBadge")) {
            $("modalPriorityBadge").className = `priority-badge priority-badge-${pClass}`;
            $("modalPriorityBadge").textContent = `${group.priority} · Score ${group.priority_score ?? 0}`;
        }
        if ($("modalPriorityReason")) {
            $("modalPriorityReason").textContent = group.priority_reason || "Evaluated by AI multi-factor priority engine.";
        }
        const factorsGrid = $("modalPriorityFactorsGrid");
        if (factorsGrid) {
            const factors = group.priority_factors || {};
            const chips = [];
            if (factors.hazard_type) chips.push(`<span class="factor-chip">🚨 Hazard: <strong>${escapeHtml(factors.hazard_type)}</strong></span>`);
            if (factors.citizen_count) chips.push(`<span class="factor-chip">👥 Reports: <strong>${factors.citizen_count} citizens (+${factors.citizen_multiplier || 0} pts)</strong></span>`);
            if (factors.days_open !== undefined) chips.push(`<span class="factor-chip">⏳ Age: <strong>${factors.days_open} days open (+${factors.age_escalation || 0} pts)</strong></span>`);
            if (factors.infrastructure_context) chips.push(`<span class="factor-chip">🏥 Proximity: <strong>${escapeHtml(factors.infrastructure_context)} (+${factors.infra_bonus || 0} pts)</strong></span>`);
            if (group.priority_override) chips.push(`<span class="factor-chip" style="background:#fff3e0;border-color:#ffcc80;">⚙️ <strong>Manually Overridden</strong> (${escapeHtml(group.priority_override_by || 'Admin')})</span>`);
            factorsGrid.innerHTML = chips.join("") || `<span class="factor-chip">Standard issue profile</span>`;
        }
        if ($("modalPriorityOverrideSelect")) {
            $("modalPriorityOverrideSelect").value = group.priority || "Medium";
        }
        if ($("modalPriorityReasonInput")) {
            $("modalPriorityReasonInput").value = "";
        }
        if ($("priorityOverrideStatus")) {
            $("priorityOverrideStatus").textContent = "";
        }

        // Linked count
        $("modalLinkedCount").textContent = (group.complaints || []).length;

        // Render Complaints List
        const list = $("modalComplaintsList");
        if (!group.complaints || group.complaints.length === 0) {
            list.innerHTML = `<div class="empty-state">No individual complaints linked yet.</div>`;
        } else {
            list.innerHTML = group.complaints.map(c => `
                <div class="linked-complaint-item">
                    <div class="linked-comp-head">
                        <span class="linked-ref">${escapeHtml(c.reference)}</span>
                        <span class="status-chip">${escapeHtml(c.status)}</span>
                    </div>
                    <h5 class="linked-comp-title">${escapeHtml(c.title)}</h5>
                    <p class="linked-comp-desc">${escapeHtml(c.description)}</p>
                    <div class="linked-comp-meta">
                        <span>📅 ${formatDate(c.created_at)}</span>
                        <span>📍 ${escapeHtml([c.address, c.ward_name].filter(Boolean).join(", ") || "Location not specified")}</span>
                        ${c.latitude && c.longitude ? `<span>🌐 ${Number(c.latitude).toFixed(4)}, ${Number(c.longitude).toFixed(4)}</span>` : ""}
                        <span>Priority: <strong>${escapeHtml(c.priority || "Medium")}</strong></span>
                    </div>
                    ${c.image_path ? `
                        <div class="linked-comp-attachment">
                            <img src="${escapeAttribute(c.image_path)}" class="thumb-img" alt="Evidence" onclick="openLightbox('${escapeAttribute(c.image_path)}')">
                            <div>
                                <small>Photo Evidence (Click to enlarge)</small>
                                ${c.image_analysis ? `<div class="vision-analysis-text">${escapeHtml(c.image_analysis)}</div>` : ""}
                            </div>
                        </div>
                    ` : ""}
                </div>
            `).join("");
        }

        // Render Notifications Trail
        const notifList = $("modalNotificationsList");
        const notifs = group.notifications || [];
        if (!notifs.length) {
            notifList.innerHTML = `<p class="muted">No notifications sent yet. Status updates will dispatch alerts to all reporting citizens.</p>`;
        } else {
            notifList.innerHTML = notifs.map(n => `
                <div class="notification-item ${escapeHtml(n.notification_type)}">
                    <span class="notif-badge">${n.notification_type === 'issue_resolved' ? '✓ RESOLVED' : 'ℹ UPDATE'}</span>
                    <div>
                        <strong>${escapeHtml(n.title)} <small>(${escapeHtml(n.complaint_reference)})</small></strong>
                        <p>${escapeHtml(n.message)}</p>
                        <small>${formatDate(n.sent_at)} · Delivered to Citizen</small>
                    </div>
                </div>
            `).join("");
        }

        // Leaflet Map inside Modal
        setTimeout(() => {
            initOrUpdateModalMap(group);
        }, 150);

    } catch (err) {
        alert("Failed to load group details: " + err.message);
    }
};

window.closeGroupModal = function() {
    const modal = $("groupModal");
    if (modal) {
        modal.classList.add("hidden");
        modal.style.display = "none";
    }
};

function initOrUpdateModalMap(group) {
    const mapEl = $("modalGroupMap");
    if (!mapEl || !window.L) return;

    if (!modalGroupMap) {
        modalGroupMap = L.map("modalGroupMap").setView(BLR, 13);
        L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
            attribution: "© OpenStreetMap contributors"
        }).addTo(modalGroupMap);
    }

    // Clear old markers
    modalMarkers.forEach(m => modalGroupMap.removeLayer(m));
    modalMarkers = [];

    const complaintsWithGeo = (group.complaints || []).filter(c => c.latitude && c.longitude);
    const bounds = [];

    complaintsWithGeo.forEach((c) => {
        const marker = L.marker([c.latitude, c.longitude]).addTo(modalGroupMap);
        marker.bindPopup(`
            <strong>${escapeHtml(c.reference)}</strong><br>
            ${escapeHtml(c.title)}<br>
            <small>${escapeHtml(c.address || c.ward_name || "")}</small>
        `);
        modalMarkers.push(marker);
        bounds.push([c.latitude, c.longitude]);
    });

    if (group.latitude && group.longitude && complaintsWithGeo.length === 0) {
        const centroidMarker = L.circleMarker([group.latitude, group.longitude], {
            radius: 8,
            color: "#1c6b4b",
            fillColor: "#c8f06a",
            fillOpacity: 0.9,
            weight: 2
        }).addTo(modalGroupMap);
        centroidMarker.bindPopup(`<strong>${escapeHtml(group.title)}</strong><br>Consolidated issue center`);
        modalMarkers.push(centroidMarker);
        bounds.push([group.latitude, group.longitude]);
    }

    modalGroupMap.invalidateSize();
    if (bounds.length > 0) {
        if (bounds.length === 1) {
            modalGroupMap.setView(bounds[0], 15);
        } else {
            modalGroupMap.fitBounds(bounds, { padding: [25, 25] });
        }
    } else {
        modalGroupMap.setView(BLR, 12);
    }
}

window.openLightbox = function(src) {
    const box = $("imageLightbox");
    const img = $("lightboxImg");
    if (box && img) {
        img.src = src;
        box.style.display = "flex";
        box.classList.remove("hidden");
    }
};

window.closeLightbox = function() {
    const box = $("imageLightbox");
    const img = $("lightboxImg");
    if (box) {
        box.classList.add("hidden");
        box.style.display = "none";
    }
    if (img) {
        img.src = "";
    }
};

window.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
        closeLightbox();
        closeGroupModal();
    }
});
