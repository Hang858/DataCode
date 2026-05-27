(function () {
    function restoreSearchFieldValue() {
        const selectElement = document.getElementById("search_field");
        if (!selectElement) {
            return;
        }

        const currentSearchField = new URLSearchParams(window.location.search).get("search_field");
        if (currentSearchField !== null) {
            selectElement.value = currentSearchField;
        }
    }

    function appendRows(tbody, columns, items) {
        items.forEach((item) => {
            const tr = document.createElement("tr");
            tr.innerHTML = columns
                .map((column) => {
                    const rawValue = item[column.key];
                    const fallbackValue = rawValue === undefined || rawValue === null || rawValue === "" ? (column.emptyText || "") : rawValue;
                    const text = String(fallbackValue);
                    return `<td title="${escapeHtml(text)}">${escapeHtml(text)}</td>`;
                })
                .join("");
            tbody.appendChild(tr);
        });
    }

    function escapeHtml(value) {
        return value
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#39;");
    }

    function initInfiniteScroll() {
        const configElement = document.getElementById("page-config");
        const tableContainer = document.querySelector(".table-container");
        const tbody = document.querySelector("tbody");

        if (!configElement || !tableContainer || !tbody) {
            return;
        }

        const endpoint = configElement.dataset.endpoint;
        const nextCursor = configElement.dataset.nextCursor;
        let columns = [];
        try {
            columns = JSON.parse(configElement.dataset.columns || "[]");
        } catch (err) {
            console.error("表格列配置解析失败:", err);
            return;
        }

        let currentCursor = nextCursor;
        let isLoading = false;
        let hasMore = Boolean(currentCursor);

        tableContainer.addEventListener("scroll", () => {
            if (tableContainer.scrollTop + tableContainer.clientHeight < tableContainer.scrollHeight - 300) {
                return;
            }
            if (isLoading || !hasMore) {
                return;
            }

            isLoading = true;
            const urlParams = new URLSearchParams(window.location.search);
            urlParams.set("ajax", "true");
            urlParams.set("search_after", currentCursor);

            fetch(`${endpoint}?${urlParams.toString()}`, {
                headers: {
                    "X-Requested-With": "XMLHttpRequest",
                },
            })
                .then((response) => response.json())
                .then((res) => {
                    if (res.data && res.data.length > 0) {
                        appendRows(tbody, columns, res.data);
                    }

                    if (res.next_cursor) {
                        currentCursor = JSON.stringify(res.next_cursor);
                    } else {
                        hasMore = false;
                    }
                })
                .catch((err) => {
                    console.error("加载数据失败:", err);
                })
                .finally(() => {
                    isLoading = false;
                });
        });
    }

    function initStatsRefresh() {
        if (document.body.dataset.statsRefreshBound === "true") {
            return;
        }
        document.body.dataset.statsRefreshBound = "true";

        document.addEventListener("click", (event) => {
            const refreshButton = event.target.closest("#stats-refresh-btn");
            if (!refreshButton) {
                return;
            }

            const countElement = document.getElementById("stats-count");
            const totalCountElement = document.getElementById("stats-total-count");
            const updatedAtElement = document.getElementById("stats-updated-at");
            const statusElement = document.getElementById("stats-refresh-status");
            const statsUrl = refreshButton.dataset.statsUrl;
            const formatter = refreshButton.dataset.statsFormatter || "raw";
            const originalText = refreshButton.textContent.trim();

            if (!statsUrl) {
                console.error("缺少统计刷新地址");
                if (statusElement) {
                    statusElement.textContent = "缺少统计刷新地址";
                }
                return;
            }

            refreshButton.disabled = true;
            refreshButton.textContent = "更新中...";
            if (statusElement) {
                statusElement.textContent = "正在更新统计...";
            }

            const url = new URL(statsUrl, window.location.origin);
            const currentParams = new URLSearchParams(window.location.search);
            currentParams.forEach((value, key) => {
                if (key !== "ajax" && key !== "search_after") {
                    url.searchParams.set(key, value);
                }
            });

            fetch(url, {
                method: "POST",
                headers: {
                    "X-Requested-With": "XMLHttpRequest",
                },
            })
                .then((response) => {
                    if (!response.ok) {
                        throw new Error(`HTTP ${response.status}`);
                    }
                    return response.json();
                })
                .then((data) => {
                    if (data.error) {
                        throw new Error(data.error);
                    }

                    if (countElement) {
                        let countValue = data.distinct_count;
                        countElement.textContent = countValue ?? "--";
                    }

                    if (totalCountElement) {
                        totalCountElement.textContent = data.total_count ?? "--";
                    }

                    if (updatedAtElement) {
                        updatedAtElement.textContent = data.updated_at || "刚刚";
                    }
                    if (statusElement) {
                        statusElement.textContent = "统计已更新";
                    }
                })
                .catch((err) => {
                    console.error("更新统计失败:", err);
                    if (statusElement) {
                        statusElement.textContent = "更新失败，请稍后重试";
                    }
                    alert("更新统计失败，请稍后重试");
                })
                .finally(() => {
                    refreshButton.disabled = false;
                    refreshButton.textContent = originalText;
                });
        });
    }

    function buildTaskUrl(template, taskId, fallbackSuffix) {
        if (template) {
            return template.replace(/\/0\/(?=$|[?#])/, `/${taskId}/`);
        }
        return `${window.location.origin}${fallbackSuffix.replace("{taskId}", taskId)}`;
    }

    function pollExportTask(taskId, statusElement) {
        const configElement = document.getElementById("page-config");
        const statusTemplate = configElement ? configElement.dataset.exportTaskStatusTemplate : "";
        const downloadTemplate = configElement ? configElement.dataset.exportTaskDownloadTemplate : "";
        const statusUrl = buildTaskUrl(statusTemplate, taskId, "/export-task/{taskId}/status/");
        const downloadUrl = buildTaskUrl(downloadTemplate, taskId, "/export-task/{taskId}/download/");

        const timer = window.setInterval(() => {
            fetch(statusUrl, {
                headers: {
                    "X-Requested-With": "XMLHttpRequest",
                },
            })
                .then((response) => response.json())
                .then((data) => {
                    if (data.error) {
                        throw new Error(data.error);
                    }

                    if (data.status === "success") {
                        window.clearInterval(timer);
                        if (statusElement) {
                            statusElement.textContent = `导出完成，共 ${data.row_count || 0} 条，开始下载`;
                        }
                        window.location.href = downloadUrl;
                        return;
                    }

                    if (data.status === "failed") {
                        window.clearInterval(timer);
                        if (statusElement) {
                            statusElement.textContent = data.error_message || "导出失败";
                        }
                        return;
                    }

                    if (statusElement) {
                        statusElement.textContent = "导出任务处理中...";
                    }
                })
                .catch((err) => {
                    window.clearInterval(timer);
                    console.error("查询导出任务失败:", err);
                    if (statusElement) {
                        statusElement.textContent = "查询导出任务失败";
                    }
                });
        }, 1500);
    }

    function initExportActions() {
        if (document.body.dataset.exportActionBound === "true") {
            return;
        }
        document.body.dataset.exportActionBound = "true";

        document.addEventListener("click", (event) => {
            const exportButton = event.target.closest("[data-export-create-url]");
            if (!exportButton) {
                return;
            }

            event.preventDefault();

            const createUrl = exportButton.dataset.exportCreateUrl;
            const statusElement = document.getElementById("export-status");
            const originalText = exportButton.textContent.trim();
            const url = new URL(createUrl, window.location.origin);
            const currentParams = new URLSearchParams(window.location.search);

            currentParams.forEach((value, key) => {
                if (key !== "ajax" && key !== "search_after") {
                    url.searchParams.set(key, value);
                }
            });

            exportButton.disabled = true;
            exportButton.textContent = "创建中...";
            if (statusElement) {
                statusElement.textContent = "正在创建导出任务...";
            }

            fetch(url, {
                method: "POST",
                headers: {
                    "X-Requested-With": "XMLHttpRequest",
                },
            })
                .then((response) => {
                    if (!response.ok) {
                        throw new Error(`HTTP ${response.status}`);
                    }
                    return response.json();
                })
                .then((data) => {
                    if (data.error) {
                        throw new Error(data.error);
                    }
                    if (statusElement) {
                        statusElement.textContent = `导出任务已创建，任务ID: ${data.task_id}`;
                    }
                    pollExportTask(data.task_id, statusElement);
                })
                .catch((err) => {
                    console.error("创建导出任务失败:", err);
                    if (statusElement) {
                        statusElement.textContent = "创建导出任务失败";
                    }
                    alert("创建导出任务失败，请稍后重试");
                })
                .finally(() => {
                    exportButton.disabled = false;
                    exportButton.textContent = originalText;
                });
        });
    }

    function initPage() {
        initStatsRefresh();
        initExportActions();
        restoreSearchFieldValue();
        initInfiniteScroll();
    }

    if (document.readyState === "loading") {
        window.addEventListener("DOMContentLoaded", initPage);
    } else {
        initPage();
    }
})();
