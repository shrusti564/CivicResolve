
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

async function api(url, options = {}) {
    const response = await fetch(API + url, options);
    const data = await response.json();
    if (!response.ok) {
        throw new Error(data.detail || "API request failed");
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
    $("latitude").value = Number(lat).toFixed(7);
    $("longitude").value = Number(lon).toFixed(7);
    $("location_source").value = source;

    $("coords").textContent =
        `Latitude ${lat.toFixed(5)} · Longitude ${lon.toFixed(5)}`;

    $("locationStatus").textContent = "Identifying Bengaluru ward...";

    if (citizenMap) {
        citizenMap.setView([lat, lon], 16);

        if (citizenMarker) citizenMarker.setLatLng([lat, lon]);
        else citizenMarker = L.marker([lat, lon]).addTo(citizenMap);
    }

    try {
        const result = await api(
            `/api/geo/ward?latitude=${lat}&longitude=${lon}`
        );

        $("wardResult").textContent = result.matched
            ? `Ward: ${result.ward_name} · Corporation: ${result.corporation} · Zone: ${result.zone}`
            : result.reason;

    } catch (error) {
        $("wardResult").textContent =
            "Ward lookup unavailable. Coordinates are retained.";
    }

    $("locationStatus").textContent = "Location selected.";

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

    $("gpsBtn").addEventListener("click", () => {
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

    $("latitude").addEventListener("change", manualCoords);
    $("longitude").addEventListener("change", manualCoords);

    $("complaintForm").addEventListener("submit", async e => {
        e.preventDefault();

        const button = e.submitter;
        button.disabled = true;
        button.textContent = "Submitting...";

        try {
            const formData = new FormData(e.currentTarget);

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
            $("submitMessage").textContent =
                `Complaint saved. Reference: ${result.reference}. This is a local academic prototype, not a government filing.`;

            e.currentTarget.reset();

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
            button.disabled = false;
            button.innerHTML = "Submit complaint <span>→</span>";
        }
    });

    $("askForm").addEventListener("submit", async e => {
        e.preventDefault();

        const box = $("answerBox");
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
                    s => `[${s.citation}] ${s.source} · ${s.path}`
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
        console.error(error);
    }
}

// ---------------- ADMIN DASHBOARD ----------------

function initAdmin() {
    if (!$("kpiTotal")) return;

    initAdminMap();

    $("refreshBtn").addEventListener("click", refreshDashboard);

    $("ingestBtn").addEventListener("click", async () => {
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

    $("tableSearch").addEventListener("input", loadTable);

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

        notice.classList.remove("hidden");
        notice.textContent =
            "HISTORICAL ANALYTICS · Bengaluru complaints, 2019–2022. These are not live CivicResolve submissions.";

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

        drawChart(
            "monthlyChart",
            "line",
            result.monthly.map(x => x.month),
            result.monthly.map(x => x.complaints)
        );

        await loadMapLayers();

    } catch (error) {
        console.error("Historical dashboard error:", error);
    }
}

// ---------------- CHARTS ----------------

function drawChart(id, type, labels, values) {
    const canvas = $(id);

    if (!canvas || !window.Chart) return;

    if (charts[id]) charts[id].destroy();

    charts[id] = new Chart(canvas, {
        type,
        data: {
            labels,
            datasets: [{
                label: "Historical complaints",
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
                x: { grid: { display: false } },
                y: { beginAtZero: true }
            }
        }
    });
}

// ---------------- COMPLAINT REGISTER ----------------

async function loadTable() {
    if (!$("complaintRows")) return;

    const query = $("tableSearch").value.toLowerCase();

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
                    <select onchange="updateComplaintStatus(${Number(x.id)},this.value)">
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
            '<tr><td colspan="7">Could not load complaints.</td></tr>';
    }
}

window.updateComplaintStatus = async (id, status) => {
    try {
        await api(`/api/complaints/${id}/status`, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ status })
        });

        await loadTable();
    } catch (error) {
        alert(error.message);
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
        const files = data.files || [];
        const sources = data.sources?.datasets || [];

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
});
