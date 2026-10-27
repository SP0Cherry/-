/* Knowledge base page: retrieval vs streaming Q&A, skill selection, teacher
   skill management and the "no material found" continue/cancel gate. All
   untrusted text is inserted via textContent / DOM nodes. */
(function () {
  "use strict";

  var api = window.CampusClaw;
  var mode = "retrieve"; // or "ask"
  var lastQuestion = "";
  var currentUser = null;
  var skills = [];
  var templates = [];
  var abortController = null;
  var answerTextNode = null;

  function el(id) {
    return document.getElementById(id);
  }

  function showMessage(kind, text) {
    var node = el("message");
    if (!text) {
      node.className = "message";
      node.textContent = "";
      return;
    }
    node.className = "message " + kind;
    node.textContent = text;
  }

  function abortCurrent() {
    if (abortController) {
      abortController.abort();
      abortController = null;
    }
  }

  function clearResults() {
    el("sources-box").textContent = "";
    el("answer-box").hidden = true;
    el("answer-box").textContent = "";
    el("gate-box").hidden = true;
    el("tool-status").hidden = true;
    el("tool-status").textContent = "";
    answerTextNode = null;
  }

  // ------------------------------------------------------------- rendering

  function renderSources(sources) {
    var box = el("sources-box");
    box.textContent = "";
    if (!sources.length) {
      var empty = document.createElement("p");
      empty.className = "hint";
      empty.textContent = "没有检索到相关内容。";
      box.appendChild(empty);
      return;
    }

    var heading = document.createElement("h2");
    heading.textContent = "资料出处（" + sources.length + "）";
    box.appendChild(heading);

    var list = document.createElement("ul");
    list.className = "source-list";
    sources.forEach(function (source) {
      var item = document.createElement("li");

      var titleLine = document.createElement("div");
      titleLine.className = "source-title";
      var link = document.createElement("a");
      link.textContent =
        source.material_name +
        (source.heading ? " · " + source.heading : "");
      link.href = source.preview_url;
      titleLine.appendChild(link);

      var scoreLine = document.createElement("span");
      scoreLine.className = "source-score";
      scoreLine.textContent = "相关度 " + source.score;
      titleLine.appendChild(document.createTextNode(" "));
      titleLine.appendChild(scoreLine);

      var snippet = document.createElement("p");
      snippet.className = "source-snippet";
      snippet.textContent = source.snippet;

      item.appendChild(titleLine);
      item.appendChild(snippet);
      list.appendChild(item);
    });
    box.appendChild(list);
  }

  function beginAnswer(retrieved) {
    var box = el("answer-box");
    box.textContent = "";
    box.hidden = false;

    if (!retrieved) {
      var marker = document.createElement("p");
      marker.className = "answer-marker";
      marker.textContent = "以下回答不依据本班课程资料，可能不满足课程要求：";
      box.appendChild(marker);
    }

    answerTextNode = document.createElement("div");
    answerTextNode.className = "answer-text";
    box.appendChild(answerTextNode);
  }

  function appendAnswer(text) {
    var box = el("answer-box");
    box.hidden = false;
    if (!answerTextNode) beginAnswer(true);
    answerTextNode.appendChild(document.createTextNode(text));
  }

  function showGate(message) {
    el("gate-text").textContent = message;
    el("gate-box").hidden = false;
  }

  function statusLabel(status) {
    if (status === "ok") return "成功";
    if (status === "denied") return "已拒绝";
    return "失败";
  }

  function renderMetaStatus(meta) {
    var box = el("tool-status");
    box.textContent = "";
    var rendered = 0;

    if (meta.template) {
      var templateLine = document.createElement("p");
      templateLine.className = "tool-line tool-ok";
      templateLine.textContent = "本次使用模板：" + meta.template.name;
      box.appendChild(templateLine);
      rendered += 1;
    }

    (meta.skills || []).forEach(function (skill) {
      var line = document.createElement("p");
      line.className = "tool-line " + (skill.hit ? "tool-ok" : "tool-muted");
      line.textContent = skill.hit
        ? "已应用技能：" + skill.name
        : "未命中技能：" + skill.name + "（本次不应用）";
      box.appendChild(line);
      rendered += 1;
    });

    (meta.tool_calls || []).forEach(function (call) {
      var line = document.createElement("p");
      line.className = "tool-line tool-" + (call.status || "error");
      var text =
        "工具 " + call.ref + "：" + statusLabel(call.status);
      if (call.reason) text += "（" + call.reason + "）";
      line.textContent = text;
      box.appendChild(line);
      rendered += 1;
    });

    box.hidden = rendered === 0;
  }

  function applyMeta(meta) {
    renderSources(meta.sources || []);
    renderMetaStatus(meta);
    if (meta.gate) {
      el("answer-box").hidden = true;
      showGate(
        meta.message ||
          "未在本班资料中检索到相关内容，是否仍要基于通用知识继续提问？"
      );
      return;
    }
    beginAnswer(!!meta.retrieved);
  }

  // ---------------------------------------------------------- skill lists

  function enabledSkills() {
    return skills.filter(function (skill) {
      return skill.enabled;
    });
  }

  function renderSkillChoices() {
    var list = el("skills-list");
    list.textContent = "";
    var items = enabledSkills();
    el("skills-empty").hidden = items.length > 0;
    if (!items.length) return;

    items.forEach(function (skill) {
      var label = document.createElement("label");
      label.className = "skill-choice";

      var input = document.createElement("input");
      input.type = "checkbox";
      input.value = String(skill.id);
      input.className = "skill-checkbox";

      var text = document.createElement("span");
      text.textContent =
        skill.name + (skill.subject ? "（" + skill.subject + "）" : "");

      label.appendChild(input);
      label.appendChild(text);
      list.appendChild(label);
    });
  }

  function selectedSkillIds() {
    var boxes = document.querySelectorAll(".skill-checkbox:checked");
    var ids = [];
    for (var i = 0; i < boxes.length; i += 1) {
      ids.push(parseInt(boxes[i].value, 10));
    }
    return ids;
  }

  function renderSkillManage() {
    var section = el("skill-manage");
    if (!currentUser || currentUser.role !== "teacher") {
      section.hidden = true;
      return;
    }
    section.hidden = false;

    var tbody = el("skills-manage-body");
    tbody.textContent = "";
    if (!skills.length) {
      var row = document.createElement("tr");
      var cell = document.createElement("td");
      cell.colSpan = 6;
      cell.className = "muted";
      cell.textContent = "本班尚未上传技能。";
      row.appendChild(cell);
      tbody.appendChild(row);
      return;
    }

    skills.forEach(function (skill) {
      var tr = document.createElement("tr");

      [
        skill.name,
        skill.subject || "—",
        (skill.keywords || []).join("、") || "—",
        (skill.tools || []).join("、") || "—",
        skill.enabled ? "启用" : "停用"
      ].forEach(function (value) {
        var td = document.createElement("td");
        td.textContent = value;
        tr.appendChild(td);
      });

      var actions = document.createElement("td");
      var button = document.createElement("button");
      button.type = "button";
      button.className = "linkish";
      button.textContent = "删除";
      button.addEventListener("click", function () {
        if (!window.confirm("确定删除技能「" + skill.name + "」？")) return;
        api.jsonRequest("/api/skills/" + skill.id, "DELETE").then(
          function (result) {
            if (!result.ok) {
              var body = result.data || {};
              throw new Error(body.message || "删除失败");
            }
            showMessage("success", "技能已删除");
            return loadSkills();
          }
        ).catch(function (error) {
          showMessage("error", error.message || "删除失败");
        });
      });
      actions.appendChild(button);
      tr.appendChild(actions);
      tbody.appendChild(tr);
    });
  }

  function loadSkills() {
    return api.jsonRequest("/api/skills", "GET").then(function (result) {
      if (!result.ok) {
        var body = result.data || {};
        throw new Error(body.message || "加载技能失败");
      }
      skills = result.data.items || [];
      renderSkillChoices();
      renderSkillManage();
    });
  }

  function initSkillManage() {
    var form = el("skill-form");
    if (!form) return;
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      var input = el("skill-file");
      if (!input.files || !input.files[0]) {
        showMessage("error", "请先选择技能文件");
        return;
      }

      var data = new FormData();
      data.append("file", input.files[0]);
      showMessage("muted", "");
      api
        .authFetch("/api/skills", { method: "POST", body: data })
        .then(function (response) {
          return response
            .json()
            .catch(function () { return null; })
            .then(function (body) {
              return { ok: response.ok, body: body };
            });
        })
        .then(function (result) {
          if (!result.ok) {
            var body = result.body || {};
            throw new Error(body.message || "上传失败");
          }
          form.reset();
          showMessage("success", "技能已上传");
          return loadSkills();
        })
        .catch(function (error) {
          showMessage("error", error.message || "上传失败");
        });
    });
  }

  // ------------------------------------------------------- template lists

  function renderTemplateChoices() {
    var list = el("template-list");
    list.textContent = "";

    function addOption(value, labelText) {
      var label = document.createElement("label");
      label.className = "skill-choice";

      var input = document.createElement("input");
      input.type = "radio";
      input.name = "template-choice";
      input.value = value;
      if (value === "") input.checked = true;

      var text = document.createElement("span");
      text.textContent = labelText;

      label.appendChild(input);
      label.appendChild(text);
      list.appendChild(label);
    }

    addOption("", "不使用模板");
    templates
      .filter(function (template) {
        return template.enabled;
      })
      .forEach(function (template) {
        addOption(String(template.id), template.name);
      });
  }

  function selectedTemplateId() {
    var box = document.querySelector(
      'input[name="template-choice"]:checked'
    );
    if (!box || box.value === "") return null;
    var id = parseInt(box.value, 10);
    return isNaN(id) ? null : id;
  }

  function renderTemplateManage() {
    var section = el("template-manage");
    if (!currentUser || currentUser.role !== "teacher") {
      section.hidden = true;
      return;
    }
    section.hidden = false;

    var tbody = el("templates-manage-body");
    tbody.textContent = "";
    if (!templates.length) {
      var row = document.createElement("tr");
      var cell = document.createElement("td");
      cell.colSpan = 5;
      cell.className = "muted";
      cell.textContent = "本班尚未上传模板。";
      row.appendChild(cell);
      tbody.appendChild(row);
      return;
    }

    templates.forEach(function (template) {
      var tr = document.createElement("tr");

      [
        template.name,
        template.description || "—",
        (template.placeholders || []).join("、") || "—",
        template.enabled ? "启用" : "停用"
      ].forEach(function (value) {
        var td = document.createElement("td");
        td.textContent = value;
        tr.appendChild(td);
      });

      var actions = document.createElement("td");
      var button = document.createElement("button");
      button.type = "button";
      button.className = "linkish";
      button.textContent = "删除";
      button.addEventListener("click", function () {
        if (!window.confirm("确定删除模板「" + template.name + "」？")) return;
        api.jsonRequest("/api/prompt-templates/" + template.id, "DELETE").then(
          function (result) {
            if (!result.ok) {
              var body = result.data || {};
              throw new Error(body.message || "删除失败");
            }
            showMessage("success", "模板已删除");
            return loadTemplates();
          }
        ).catch(function (error) {
          showMessage("error", error.message || "删除失败");
        });
      });
      actions.appendChild(button);
      tr.appendChild(actions);
      tbody.appendChild(tr);
    });
  }

  function loadTemplates() {
    return api.jsonRequest("/api/prompt-templates", "GET").then(function (result) {
      if (!result.ok) {
        var body = result.data || {};
        throw new Error(body.message || "加载模板失败");
      }
      templates = result.data.items || [];
      renderTemplateChoices();
      renderTemplateManage();
    });
  }

  function initTemplateManage() {
    var form = el("template-form");
    if (!form) return;
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      var input = el("template-file");
      if (!input.files || !input.files[0]) {
        showMessage("error", "请先选择模板文件");
        return;
      }

      var data = new FormData();
      data.append("file", input.files[0]);
      showMessage("muted", "");
      api
        .authFetch("/api/prompt-templates", { method: "POST", body: data })
        .then(function (response) {
          return response
            .json()
            .catch(function () { return null; })
            .then(function (body) {
              return { ok: response.ok, body: body };
            });
        })
        .then(function (result) {
          if (!result.ok) {
            var body = result.body || {};
            throw new Error(body.message || "上传失败");
          }
          form.reset();
          showMessage("success", "模板已上传");
          return loadTemplates();
        })
        .catch(function (error) {
          showMessage("error", error.message || "上传失败");
        });
    });
  }

  // --------------------------------------------------------------- SSE

  function parseEventBlock(block) {
    var eventName = "message";
    var dataLines = [];
    block.split(/\r?\n/).forEach(function (line) {
      if (line.indexOf("event:") === 0) {
        eventName = line.slice(6).trim();
      } else if (line.indexOf("data:") === 0) {
        dataLines.push(line.slice(5).trim());
      }
    });
    if (!dataLines.length) return null;
    return { event: eventName, data: dataLines.join("\n") };
  }

  function consumeSSE(response, onEvent) {
    var reader = response.body.getReader();
    var decoder = new TextDecoder("utf-8");
    var buffer = "";

    function processBuffer(final) {
      var parts = buffer.split(/\r?\n\r?\n/);
      buffer = parts.pop() || "";
      parts.forEach(function (block) {
        var parsed = parseEventBlock(block);
        if (parsed) onEvent(parsed.event, parsed.data);
      });
      if (final && buffer.trim()) {
        var last = parseEventBlock(buffer);
        if (last) onEvent(last.event, last.data);
        buffer = "";
      }
    }

    function pump() {
      return reader.read().then(function (result) {
        if (result.done) {
          processBuffer(true);
          return;
        }
        buffer += decoder.decode(result.value, { stream: true });
        processBuffer(false);
        return pump();
      });
    }

    return pump();
  }

  function doAsk(q, force) {
    clearResults();
    abortCurrent();
    var controller = new AbortController();
    abortController = controller;

    var payload = { q: q, force: !!force };
    var ids = selectedSkillIds();
    if (ids.length) payload.skill_ids = ids;
    var templateId = selectedTemplateId();
    if (templateId !== null) payload.template_id = templateId;

    var streamError = null;
    return api
      .authFetch("/api/kb/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
        signal: controller.signal
      })
      .then(function (response) {
        if (!response.ok) {
          return response
            .json()
            .catch(function () { return null; })
            .then(function (body) {
              throw new Error((body && body.message) || "问答请求失败");
            });
        }
        if (!response.body) throw new Error("当前浏览器不支持流式响应");

        return consumeSSE(response, function (event, raw) {
          var data = {};
          try {
            data = JSON.parse(raw);
          } catch (error) {
            return;
          }
          if (event === "meta") {
            applyMeta(data);
          } else if (event === "delta") {
            appendAnswer(data.text || "");
          } else if (event === "error") {
            streamError = new Error(data.message || "生成回答时发生错误");
            showMessage("error", streamError.message);
          }
        });
      })
      .then(function () {
        if (streamError) throw streamError;
      })
      .finally(function () {
        // Drop the controller once the stream settles: aborting a finished
        // request only produces a console net::ERR_ABORTED.
        if (abortController === controller) abortController = null;
      });
  }

  function doSearch(q) {
    clearResults();
    abortCurrent();
    return api
      .authFetch("/api/kb/search?q=" + encodeURIComponent(q))
      .then(function (response) {
        return response.json().then(function (body) {
          return { ok: response.ok, body: body };
        });
      })
      .then(function (result) {
        if (!result.ok) throw new Error(result.body.message);
        renderSources(result.body.sources || []);
      });
  }

  function setMode(next) {
    mode = next;
    var isAsk = next === "ask";
    el("mode-retrieve").classList.toggle("active", !isAsk);
    el("mode-ask").classList.toggle("active", isAsk);
    el("submit-btn").textContent = isAsk ? "提问" : "检索";
    el("mode-hint").textContent = isAsk
      ? "问答模式：先检索本班资料，命中则基于资料作答并给出出处；可选择技能，未命中可由你决定是否继续。"
      : "检索模式：仅返回本班资料中的相关片段与出处。";
    el("skills-box").hidden = !isAsk;
    el("template-box").hidden = !isAsk;
    abortCurrent();
    clearResults();
  }

  // --------------------------------------------------------------- init

  document.addEventListener("DOMContentLoaded", function () {
    el("logout-btn").addEventListener("click", function () {
      api.clearToken();
      location.assign("/login");
    });

    el("mode-retrieve").addEventListener("click", function () {
      setMode("retrieve");
    });
    el("mode-ask").addEventListener("click", function () {
      setMode("ask");
    });

    el("query-form").addEventListener("submit", function (event) {
      event.preventDefault();
      var q = el("query-input").value.trim();
      if (!q) {
        showMessage("error", "请输入问题");
        return;
      }
      showMessage("", "");
      lastQuestion = q;
      var action = mode === "ask" ? doAsk(q, false) : doSearch(q);
      action.catch(function (error) {
        if (error && error.name === "AbortError") return;
        showMessage("error", error.message || "请求失败，请稍后重试");
      });
    });

    el("gate-continue").addEventListener("click", function () {
      el("gate-box").hidden = true;
      doAsk(lastQuestion, true).catch(function (error) {
        if (error && error.name === "AbortError") return;
        showMessage("error", error.message || "请求失败，请稍后重试");
      });
    });

    el("gate-cancel").addEventListener("click", function () {
      el("gate-box").hidden = true;
    });

    api
      .jsonRequest("/api/auth/me", "GET")
      .then(function (result) {
        if (!result.ok) throw new Error();
        currentUser = result.data.user;
        el("user-badge").textContent =
          currentUser.username +
          "（" + (currentUser.role === "teacher" ? "教师" : "学生") +
          (currentUser.class ? " · " + currentUser.class.name : "") + "）";
        if (currentUser.role === "teacher") initSkillManage();
        if (currentUser.role === "teacher") initTemplateManage();
        return Promise.all([loadSkills(), loadTemplates()]);
      })
      .catch(function (error) {
        if (error && error.name === "AbortError") return;
        showMessage("error", error.message || "登录状态失效，请重新登录");
      });
  });
})();
