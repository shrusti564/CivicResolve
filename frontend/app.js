
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
            $("submitMessage").innerHTML = `Complaint saved. Reference: <strong>${escapeHtml(result.reference)}</strong>. <a href="/track?reference=${encodeURIComponent(result.reference)}">Track this complaint</a>. This is a local academic prototype, not a government filing.`;

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

// ---------------- ADMIN DASHBOARD ----------------

function initAdmin() {
    if (!$("kpiTotal")) return;

    initAdminMap();

    $("refreshBtn")?.addEventListener("click", refreshDashboard);

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

    refreshDashboard();
    loadTable();
    loadDatasets();
}

async function refreshDashboard() {
    try {
        const result = await api("/api/dashboard/historical");
        const k = result.kpis;

        $("kpiTotal").textContent =
            k.total_complaints.toLocaleString("en-IN");

        $("kpiOpen").textContent =
            k.open_complaints.toLocaleString("en-IN");

        $("kpiResolved").textContent =
            k.resolved_complaints.toLocaleString("en-IN");

        $("kpiRate").textContent =
            k.resolution_rate_percent + "%";

        $("kpiMonth").textContent =
            "2019–2022";

        $("kpiGeo").textContent =
            k.records_with_gps.toLocaleString("en-IN");

        const notice = $("demoNotice");

        notice?.remove();

        drawChart(
            "categoryChart",
            "bar",
            result.categories.slice(0, 10).map(x => x.category),
            result.categories.slice(0, 10).map(x => x.complaints)
        );

        drawChart(
            "statusChart",
            "doughnut",
            result.statuses.map(x => x.status),
            result.statuses.map(x => x.complaints)
        );

        const yearly = new Map();
        result.monthly.forEach(x => {
            const year = String(x.month).slice(0, 4);
            yearly.set(year, (yearly.get(year) || 0) + x.complaints);
        });
        const years = Array.from({ length: 8 }, (_, i) => String(2019 + i));
        drawChart("monthlyChart", "line", years, years.map(year => yearly.get(year) || 0), "Complaints by year");

        await loadMapLayers();

    } catch (error) {
        ["kpiTotal", "kpiOpen", "kpiResolved", "kpiRate", "kpiMonth", "kpiGeo"].forEach(id => {
            if ($(id)) $(id).textContent = "Unavailable";
        });
        const notice = $("demoNotice");
        notice?.remove();
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
            <tr><td colspan="7" class="empty-state">No matching complaints.</td></tr>
        `;

    } catch (error) {
        $("complaintRows").innerHTML =
            `<tr><td colspan="7">Could not load live complaints: ${escapeHtml(error.message)}</td></tr>`;
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

        // Load the 369 GBA ward polygons.
        const wards = await api("/api/geo/wards");

        wardLayer = L.geoJSON(wards, {
            style: {
                color: "#287451",
                weight: 1,
                fillColor: "#8ab69a",
                fillOpacity: 0.08
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

        // Load historical complaint coordinates.
        const geo = await api("/api/dashboard/historical/geo");

        const renderer = L.canvas({ padding: 0.5 });

        historicalLayer = L.layerGroup();

        // Limit visible markers to maintain browser performance.
        const points = geo.points;
        const maxMarkers = 4000;
        const step = Math.max(1, Math.ceil(points.length / maxMarkers));

        points.forEach((p, index) => {
            if (index % step !== 0) return;

            if (!Number.isFinite(p.latitude) ||
                !Number.isFinite(p.longitude)) return;

            L.circleMarker(
                [p.latitude, p.longitude],
                {
                    renderer,
                    radius: 3,
                    color: "#C47A31",
                    fillColor: "#E5A45E",
                    fillOpacity: 0.65,
                    weight: 1
                }
            ).bindPopup(`
                <strong>Historical complaint</strong><br>
                ${escapeHtml(p.category_title)}<br>
                Ward: ${escapeHtml(p.ward_title)}<br>
                Status: ${escapeHtml(p.complaint_status_title)}
            `).addTo(historicalLayer);
        });

        historicalLayer.addTo(adminMap);

        const bounds = wardLayer.getBounds();

        if (bounds.isValid()) {
            adminMap.fitBounds(bounds, { padding: [15, 15] });
        }

        const mapNote = document.querySelector(".map-panel .muted");

        if (mapNote) {
            mapNote.textContent =
                `GBA 2025 ward boundaries · ${geo.total_points.toLocaleString("en-IN")} historical GPS records · ${Math.min(maxMarkers, points.length).toLocaleString("en-IN")} sampled map markers displayed.`;
        }

    } catch (error) {
        console.error("Map loading error:", error);
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
    $("trackingResult").innerHTML = `
      <section class="tracking-latest panel"><div><span class="step">LATEST UPDATE</span><h2>${escapeHtml(statusLabel)}</h2><p>${latest?.remarks ? escapeHtml(latest.remarks) : "No additional action note has been recorded."}</p>${latest ? `<small>Updated ${formatDate(latest.created_at)}${latest.updated_by ? ` · ${escapeHtml(latest.updated_by)}` : ""}</small>` : ""}</div><span class="status-chip">${escapeHtml(statusLabel)}</span></section>
      <section class="panel tracking-details"><div class="panel-head"><div><span class="step">COMPLAINT DETAILS</span><h3>${escapeHtml(c.title)}</h3></div><span class="status-chip">${escapeHtml(statusLabel)}</span></div>
        <p class="tracking-description">${escapeHtml(c.description)}</p><div class="tracking-facts">
          ${trackingFact("Complaint ID", c.reference)}${trackingFact("Category", c.category)}${trackingFact("Location / Ward", location)}${trackingFact("Date submitted", formatDate(c.created_at))}${trackingFact("Last updated", formatDate(c.updated_at))}${trackingFact("Assigned department / officer", c.assigned_department || c.assigned_officer || "Not recorded")}
        </div>
      </section>
      <section class="panel tracking-progress"><div class="panel-head"><div><span class="step">PROGRESS</span><h3>What happens next</h3><p>Stages appear as updates are recorded for this complaint.</p></div><strong class="progress-percent">${Math.round(progress)}%</strong></div><div class="progress-track" role="progressbar" aria-label="Complaint progress" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${Math.round(progress)}"><span style="width:${progress}%"></span></div>${current === "Rejected" ? `<p class="tracking-rejected">This complaint was marked Rejected.${latest?.remarks ? ` ${escapeHtml(latest.remarks)}` : ""}</p>` : `<ol class="tracking-timeline">${stages}</ol>`}</section>
      <section class="panel tracking-resolution"><span class="step">RESOLUTION EVIDENCE</span><h3>Department remarks and photos</h3>${latest?.remarks ? `<p>${escapeHtml(latest.remarks)}</p>` : `<p>No department remarks have been recorded.</p>`}${image ? `<img class="resolution-photo" src="${escapeAttribute(image)}" alt="Complaint resolution evidence">` : `<p class="muted">No resolution photo is available.</p>`}</section>`;
}

function trackingFact(label, value) {
    return `<div class="tracking-fact"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value || "Not recorded")}</strong></div>`;
}

function formatDate(value) {
    if (!value) return "Not recorded";
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? "Not recorded" : date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}
