/* Materials page: identity bootstrap, list render, upload, bearer download.
   All untrusted values are inserted via textContent / DOM nodes. */
(function () {
  "use strict";

  var api = window.CampusClaw;
  var previewableExts = [];

  function extOfName(name) {
    var idx = (name || "").lastIndexOf(".");
    return idx >= 0 ? name.slice(idx + 1).toLowerCase() : "";
  }

  function showMessage(kind, text) {
    var el = document.getElementById("message");
    if (!text) {
      el.className = "message";
      el.textContent = "";
      return;
    }
    el.className = "message " + kind;
    el.textContent = text;
  }

  function humanSize(bytes) {
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
    return (bytes / (1024 * 1024)).toFixed(1) + " MB";
  }

  function fmtTime(iso) {
    var d = new Date(iso);
    if (isNaN(d.getTime())) return iso;
    function pad(n) { return n < 10 ? "0" + n : "" + n; }
    return (
      d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate()) +
      " " + pad(d.getHours()) + ":" + pad(d.getMinutes())
    );
  }

  function renderBadge(user) {
    var badge = document.getElementById("user-badge");
    badge.textContent =
      user.username +
      "（" + (user.role === "teacher" ? "教师" : "学生") +
      " · " + user.class.name + "）";
    document.getElementById("class-title").textContent =
      user.class.name + " · 教学材料";
    // Visibility is derived from the server-verified role on every load;
    // never rely solely on the HTML's default hidden style.
    document.getElementById("upload-form").style.display =
      user.role === "teacher" ? "" : "none";
    document.getElementById("mcp-section").hidden = user.role !== "teacher";
  }

  // ------------------------------------------------------- MCP servers (teacher)

  function renderMcpServers(items) {
    var tbody = document.getElementById("mcp-servers-body");
    tbody.textContent = "";
    if (!items.length) {
      var emptyRow = document.createElement("tr");
      var emptyCell = document.createElement("td");
      emptyCell.colSpan = 5;
      emptyCell.className = "muted";
      emptyCell.textContent = "尚未登记 MCP 服务器。";
      emptyRow.appendChild(emptyCell);
      tbody.appendChild(emptyRow);
      return;
    }

    items.forEach(function (server) {
      var tr = document.createElement("tr");

      var tdName = document.createElement("td");
      tdName.textContent = server.name;
      tr.appendChild(tdName);

      var tdUrl = document.createElement("td");
      tdUrl.textContent = server.base_url;
      tr.appendChild(tdUrl);

      var tdStatus = document.createElement("td");
      tdStatus.textContent = server.connected ? "已连接" : "未连接";
      tr.appendChild(tdStatus);

      var tdTools = document.createElement("td");
      var tools = server.tools || [];
      tdTools.textContent = tools.length
        ? tools.map(function (tool) { return tool.name; }).join("、")
        : "—";
      if (server.last_error) {
        var err = document.createElement("div");
        err.className = "mcp-error";
        err.textContent = server.last_error;
        tdTools.appendChild(err);
      }
      tr.appendChild(tdTools);

      var tdActions = document.createElement("td");
      if (server.connected) {
        tdActions.appendChild(mcpButton("断开", function () {
          runMcpAction(server.id, "disconnect", "已断开，工具缓存已清空");
        }));
      } else {
        tdActions.appendChild(mcpButton("连接", function () {
          runMcpAction(server.id, "connect", "连接成功，工具清单已缓存");
        }));
      }
      tdActions.appendChild(mcpButton("删除", function () {
        if (!window.confirm("确定删除「" + server.name + "」？")) return;
        api.jsonRequest("/api/mcp/servers/" + server.id, "DELETE").then(
          function (result) {
            if (!result.ok) {
              var body = result.data || {};
              throw new Error(body.message || "删除失败");
            }
            showMessage("success", "已删除");
            return loadMcpServers();
          }
        ).catch(function (error) {
          showMessage("error", error.message || "删除失败");
        });
      }));
      tr.appendChild(tdActions);

      tbody.appendChild(tr);
    });
  }

  function mcpButton(text, handler) {
    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "linkish";
    btn.textContent = text;
    btn.addEventListener("click", handler);
    return btn;
  }

  function runMcpAction(serverId, action, successText) {
    showMessage("muted", "");
    api
      .jsonRequest("/api/mcp/servers/" + serverId + "/" + action, "POST")
      .then(function (result) {
        if (!result.ok) {
          var body = result.data || {};
          throw new Error(body.message || "操作失败");
        }
        showMessage("success", successText);
        return loadMcpServers();
      })
      .catch(function (error) {
        showMessage("error", error.message || "操作失败，请稍后重试");
      });
  }

  function loadMcpServers() {
    return api.jsonRequest("/api/mcp/servers", "GET").then(function (result) {
      if (!result.ok) {
        var body = result.data || {};
        throw new Error(body.message || "加载 MCP 服务器失败");
      }
      renderMcpServers(result.data.items || []);
    });
  }

  // -------------------------------------------------------- MCP audit (teacher)

  var AUDIT_PAGE_SIZE = 20;
  var auditOffset = 0;
  var AUDIT_STATUS_LABELS = { ok: "成功", denied: "拒绝", error: "失败" };
  var AUDIT_STATUS_CLASSES = {
    ok: "tool-ok",
    denied: "tool-denied",
    error: "tool-error"
  };

  function appendAuditRows(items, reset) {
    var tbody = document.getElementById("audit-body");
    if (reset) {
      tbody.textContent = "";
      auditOffset = 0;
    }
    items.forEach(function (item) {
      var tr = document.createElement("tr");

      var tdTime = document.createElement("td");
      tdTime.textContent = fmtTime(item.created_at);
      tr.appendChild(tdTime);

      var tdUser = document.createElement("td");
      tdUser.textContent = item.username;
      tr.appendChild(tdUser);

      var tdRef = document.createElement("td");
      tdRef.textContent = item.ref;
      tr.appendChild(tdRef);

      var tdStatus = document.createElement("td");
      var badge = document.createElement("span");
      badge.className =
        AUDIT_STATUS_CLASSES[item.status] || "tool-muted";
      badge.textContent = AUDIT_STATUS_LABELS[item.status] || item.status;
      tdStatus.appendChild(badge);
      tr.appendChild(tdStatus);

      var tdReason = document.createElement("td");
      tdReason.textContent = item.reason || "—";
      tr.appendChild(tdReason);

      tbody.appendChild(tr);
      auditOffset += 1;
    });

    if (!tbody.children.length) {
      var emptyRow = document.createElement("tr");
      var emptyCell = document.createElement("td");
      emptyCell.colSpan = 5;
      emptyCell.className = "muted";
      emptyCell.textContent = "暂无工具调用记录。";
      emptyRow.appendChild(emptyCell);
      tbody.appendChild(emptyRow);
    }
  }

  function loadAudit(reset) {
    var offset = reset ? 0 : auditOffset;
    return api
      .jsonRequest(
        "/api/mcp/audit?limit=" + AUDIT_PAGE_SIZE + "&offset=" + offset,
        "GET"
      )
      .then(function (result) {
        if (!result.ok) {
          var body = result.data || {};
          throw new Error(body.message || "加载审计失败");
        }
        appendAuditRows(result.data.items || [], reset);
        document.getElementById("audit-more-btn").hidden = !result.data.has_more;
      });
  }

  function initMcp() {
    var form = document.getElementById("mcp-form");
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      var payload = {
        name: document.getElementById("mcp-name").value.trim(),
        base_url: document.getElementById("mcp-base-url").value.trim()
      };
      var token = document.getElementById("mcp-token").value.trim();
      if (token) payload.auth_token = token;

      api.jsonRequest("/api/mcp/servers", "POST", payload).then(
        function (result) {
          if (!result.ok) {
            var body = result.data || {};
            throw new Error(body.message || "登记失败");
          }
          form.reset();
          showMessage("success", "服务器已登记，请点击「连接」缓存工具清单");
          return loadMcpServers();
        }
      ).catch(function (error) {
        showMessage("error", error.message || "登记失败");
      });
    });
    document
      .getElementById("audit-refresh-btn")
      .addEventListener("click", function () {
        loadAudit(true).catch(function (error) {
          showMessage("error", error.message || "加载审计失败");
        });
      });
    document
      .getElementById("audit-more-btn")
      .addEventListener("click", function () {
        loadAudit(false).catch(function (error) {
          showMessage("error", error.message || "加载审计失败");
        });
      });

    loadMcpServers().catch(function (error) {
      showMessage("error", error.message || "加载 MCP 服务器失败");
    });
    loadAudit(true).catch(function (error) {
      showMessage("error", error.message || "加载审计失败");
    });
  }

  function renderMaterials(items) {
    var tbody = document.getElementById("materials-body");
    tbody.textContent = "";
    if (!items.length) {
      var tr = document.createElement("tr");
      var td = document.createElement("td");
      td.colSpan = 6;
      td.className = "muted";
      td.textContent = "本班暂无材料。";
      tr.appendChild(td);
      tbody.appendChild(tr);
      return;
    }

    items.forEach(function (m) {
      var tr = document.createElement("tr");

      var tdName = document.createElement("td");
      tdName.textContent = m.original_name;
      tr.appendChild(tdName);

      var tdType = document.createElement("td");
      tdType.textContent = m.mime_type;
      tr.appendChild(tdType);

      var tdSize = document.createElement("td");
      tdSize.textContent = humanSize(m.size_bytes);
      tr.appendChild(tdSize);

      var tdUploader = document.createElement("td");
      tdUploader.textContent = m.uploader;
      tr.appendChild(tdUploader);

      var tdTime = document.createElement("td");
      tdTime.textContent = fmtTime(m.created_at);
      tr.appendChild(tdTime);

      var tdActions = document.createElement("td");

      if (previewableExts.indexOf(extOfName(m.original_name)) >= 0) {
        var previewBtn = document.createElement("button");
        previewBtn.type = "button";
        previewBtn.className = "linkish";
        previewBtn.textContent = "预览";
        previewBtn.addEventListener("click", function () {
          location.assign("/materials/" + m.id + "/preview");
        });
        tdActions.appendChild(previewBtn);
      }

      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "linkish";
      btn.textContent = "下载";
      btn.addEventListener("click", function () {
        downloadMaterial(m.id, m.original_name);
      });
      tdActions.appendChild(btn);
      tr.appendChild(tdActions);

      tbody.appendChild(tr);
    });
  }

  function loadConfig() {
    return api.authFetch("/api/config").then(function (response) {
      if (!response.ok) return null;
      return response.json();
    }).then(function (cfg) {
      if (!cfg) return;
      var allowed = cfg.allowed_extensions || [];
      previewableExts = cfg.previewable_extensions || [];
      var input = document.getElementById("file-input");
      input.setAttribute(
        "accept",
        allowed.map(function (e) { return "." + e; }).join(",")
      );
      document.getElementById("format-hint").textContent =
        "允许类型：" + allowed.join(" / ") +
        "（" + previewableExts.join("、") + " 支持在线预览），单个文件不超过 20MB";
    });
  }

  function loadMaterials() {
    return api.authFetch("/api/materials").then(function (response) {
      if (!response.ok) return null;
      return response.json();
    }).then(function (data) {
      if (data) renderMaterials(data.items || []);
    });
  }

  function downloadMaterial(id, filename) {
    api
      .authFetch("/api/materials/" + id + "/download")
      .then(function (response) {
        if (!response.ok) throw new Error("download failed");
        return response.blob();
      })
      .then(function (blob) {
        var url = URL.createObjectURL(blob);
        var a = document.createElement("a");
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
      })
      .catch(function () {
        showMessage("error", "下载失败，请重试");
      });
  }

  function initUpload() {
    var form = document.getElementById("upload-form");
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      var input = document.getElementById("file-input");
      if (!input.files || !input.files[0]) {
        showMessage("error", "请先选择文件");
        return;
      }
      var data = new FormData();
      data.append("file", input.files[0]);
      showMessage("muted", "");
      api
        .authFetch("/api/materials/upload", { method: "POST", body: data })
        .then(function (response) {
          return response.json().catch(function () { return null; }).then(function (body) {
            return { ok: response.ok, body: body };
          });
        })
        .then(function (result) {
          if (result.ok) {
            showMessage("success", "上传成功");
            form.reset();
            return loadMaterials();
          }
          var msg =
            (result.body && (result.body.message || result.body.error)) ||
            "上传失败";
          showMessage("error", msg);
        })
        .catch(function () {
          showMessage("error", "网络错误，请稍后再试");
        });
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.getElementById("logout-btn").addEventListener("click", function () {
      api.clearToken();
      location.assign("/login");
    });

    api
      .jsonRequest("/api/auth/me", "GET")
      .then(function (result) {
        if (!result.ok || !result.data || !result.data.user) {
          // 401 path already redirects via authFetch; handle oddities too.
          api.clearToken();
          location.assign("/login");
          return;
        }
        renderBadge(result.data.user);
        initUpload();
        if (result.data.user.role === "teacher") {
          initMcp();
        }
        // Config must load before rendering so preview buttons are decided.
        return loadConfig().then(loadMaterials);
      })
      .catch(function () {
        showMessage("error", "数据加载失败，请刷新重试");
      });
  });
})();
