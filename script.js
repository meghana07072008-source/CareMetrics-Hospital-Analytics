
const API_URL = "http://127.0.0.1:5000";

async function fetchJSON(endpoint) {
    const response = await fetch(`${API_URL}${endpoint}`);

    if (!response.ok) {
        throw new Error(`${endpoint} returned ${response.status}`);
    }

    const data = await response.json();

    if (data && data.error) {
        throw new Error(data.error);
    }

    return data;
}

async function loadDashboard() {
    const refreshButton = document.getElementById("refresh-button");
    const connectionStatus = document.getElementById("connection-status");
    const backendStatus = document.getElementById("backend-status");
    const databaseStatus = document.getElementById("database-status");
    const departmentList = document.getElementById("department-list");

    if (refreshButton) {
        refreshButton.disabled = true;
        refreshButton.textContent = "Loading...";
    }

    if (connectionStatus) {
        connectionStatus.textContent = "Connecting...";
    }

    if (backendStatus) backendStatus.textContent = "Checking...";
    if (databaseStatus) databaseStatus.textContent = "Checking...";

    try {
        // Step 1: Check the Flask backend
        await fetchJSON("/");

        if (backendStatus) backendStatus.textContent = "Connected";

        // Step 2: Load the summary independently
        const summary = await fetchJSON("/api/summary");

        document.getElementById("total-patients").textContent =
            summary.total_patients ?? 0;

        document.getElementById("total-visits").textContent =
            summary.total_visits ?? 0;

        document.getElementById("total-departments").textContent =
            summary.total_departments ?? 0;

        if (databaseStatus) databaseStatus.textContent = "Connected";

        // Step 3: Load departments independently
        try {
            const departments = await fetchJSON("/api/departments");

            if (!Array.isArray(departments)) {
                throw new Error("Unexpected departments response");
            }

            let workload = [];

            // Workload is optional; it should not break the whole dashboard.
            try {
                const result = await fetchJSON(
                    "/api/analysis/department-workload"
                );

                workload = Array.isArray(result)
                    ? result
                    : (result.data || result.results || []);
            } catch (error) {
                console.warn("Workload unavailable:", error.message);
            }

            if (departmentList) {
                departmentList.replaceChildren();

                if (departments.length === 0) {
                    departmentList.textContent =
                        "No departments found.";
                } else {
                    departments.forEach(department => {
                        const row = document.createElement("div");
                        row.className = "info-row";

                        const name = document.createElement("span");
                        name.textContent = department.department_name;

                        const matching = workload.find(item =>
                            item.department_name === department.department_name
                        );

                        const count = document.createElement("strong");

                        if (matching) {
                            count.textContent =
                                `${matching.total_visits ?? matching.visit_count ?? 0} visits`;
                        } else {
                            count.textContent = "Visit count unavailable";
                        }

                        row.append(name, count);
                        departmentList.appendChild(row);
                    });
                }
            }
        } catch (error) {
            console.error("Department loading error:", error);

            if (departmentList) {
                departmentList.textContent =
                    "Summary loaded, but departments could not be loaded.";
            }
        }

        if (connectionStatus) {
            connectionStatus.textContent = "Backend connected";
        }

    } catch (error) {
        console.error("Dashboard connection error:", error);

        if (connectionStatus) {
            connectionStatus.textContent = "Connection error";
        }

        if (backendStatus) {
            backendStatus.textContent = "Connection failed";
        }

        if (databaseStatus) {
            databaseStatus.textContent = "Check API connection";
        }

        if (departmentList) {
            departmentList.textContent =
                "Unable to connect. Check that Flask is running and the API URL is correct.";
        }
    } finally {
        if (refreshButton) {
            refreshButton.disabled = false;
            refreshButton.textContent = "↻ Refresh Data";
        }
    }
}

loadDashboard();
