/* Material preview: fetch class-scoped content with a bearer token and render
   txt as plain text or md via a small DOM renderer. Nothing is injected with
   innerHTML, so material scripts can never execute. */
(function () {
  "use strict";

  var api = window.CampusClaw;

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

  /* Shared slug algorithm (must match app/kb/chunking.py slugify). */
  function slugify(s) {
    return s
      .toLowerCase()
      .replace(/[^\p{L}\p{N}\s-]/gu, "") // strip punctuation, keep CJK/alnum
      .trim()
      .replace(/\s+/g, "-")
      .replace(/-+/g, "-")
      .replace(/^-+|-+$/g, "");
  }

  // ------------------------------------------------------------- inline md

  var INLINE_RE =
    /(`[^`]+`)|(\*\*[\s\S]+?\*\*|__[\s\S]+?__)|(\*[^*]+\*|_[^_]+_)|(\[[^\]]+\]\((https?:\/\/[^)\s]+)\))/g;

  function renderInline(parent, text) {
    var last = 0;
    var match;
    INLINE_RE.lastIndex = 0;
    function pushLiteral(t) {
      if (t) parent.appendChild(document.createTextNode(t));
    }
    while ((match = INLINE_RE.exec(text)) !== null) {
      pushLiteral(text.slice(last, match.index));
      var token = match[0];
      var node;
      if (match[1]) {
        node = document.createElement("code");
        node.textContent = token.slice(1, -1);
      } else if (match[2]) {
        node = document.createElement("strong");
        node.textContent = token.slice(2, -2);
      } else if (match[3]) {
        node = document.createElement("em");
        node.textContent = token.slice(1, -1);
      } else if (match[4]) {
        node = document.createElement("a");
        node.textContent = token.match(/\[([^\]]+)\]/)[1];
        node.href = match[5];
        node.target = "_blank";
        node.rel = "noopener noreferrer";
      }
      if (node) parent.appendChild(node);
      last = INLINE_RE.lastIndex;
    }
    pushLiteral(text.slice(last));
  }

  // ------------------------------------------------------------- block md

  function isHeading(line) {
    return /^(#{1,6})\s+/.test(line);
  }

  function renderMarkdown(container, text) {
    var lines = text.split("\n");
    var i = 0;

    function flushParagraph(buf) {
      if (!buf.length) return;
      var p = document.createElement("p");
      renderInline(p, buf.join(" "));
      container.appendChild(p);
    }

    while (i < lines.length) {
      var line = lines[i];

      if (/^```/.test(line)) {
        var codeLines = [];
        i++;
        while (i < lines.length && !/^```/.test(lines[i])) {
          codeLines.push(lines[i]);
          i++;
        }
        var pre = document.createElement("pre");
        var code = document.createElement("code");
        code.textContent = codeLines.join("\n");
        pre.appendChild(code);
        container.appendChild(pre);
        i++; // skip closing fence
        continue;
      }

      if (isHeading(line)) {
        var m = line.match(/^(#{1,6})\s+(.*)$/);
        var level = m[1].length;
        var h = document.createElement("h" + level);
        h.id = slugify(m[2]);
        renderInline(h, m[2]);
        container.appendChild(h);
        i++;
        continue;
      }

      if (/^>\s?/.test(line)) {
        var quote = document.createElement("blockquote");
        var quoteLines = [];
        while (i < lines.length && /^>\s?/.test(lines[i])) {
          quoteLines.push(lines[i].replace(/^>\s?/, ""));
          i++;
        }
        renderInline(quote, quoteLines.join(" "));
        container.appendChild(quote);
        continue;
      }

      if (/^\s*[-*+]\s+/.test(line)) {
        var ul = document.createElement("ul");
        while (i < lines.length && /^\s*[-*+]\s+/.test(lines[i])) {
          var li = document.createElement("li");
          renderInline(li, lines[i].replace(/^\s*[-*+]\s+/, ""));
          ul.appendChild(li);
          i++;
        }
        container.appendChild(ul);
        continue;
      }

      if (/^\s*\d+\.\s+/.test(line)) {
        var ol = document.createElement("ol");
        while (i < lines.length && /^\s*\d+\.\s+/.test(lines[i])) {
          var oli = document.createElement("li");
          renderInline(oli, lines[i].replace(/^\s*\d+\.\s+/, ""));
          ol.appendChild(oli);
          i++;
        }
        container.appendChild(ol);
        continue;
      }

      if (/^\s*$/.test(line)) {
        i++;
        continue;
      }

      var paragraph = [];
      while (
        i < lines.length &&
        !/^\s*$/.test(lines[i]) &&
        !isHeading(lines[i]) &&
        !/^```/.test(lines[i]) &&
        !/^>\s?/.test(lines[i]) &&
        !/^\s*[-*+]\s+/.test(lines[i]) &&
        !/^\s*\d+\.\s+/.test(lines[i])
      ) {
        paragraph.push(lines[i]);
        i++;
      }
      flushParagraph(paragraph);
    }
  }

  // ------------------------------------------------------------------ txt

  function renderTxt(container, text) {
    var pre = document.createElement("pre");
    text.split("\n").forEach(function (line, idx) {
      var span = document.createElement("span");
      span.id = "L" + (idx + 1);
      span.textContent = line;
      pre.appendChild(span);
      pre.appendChild(document.createTextNode("\n"));
    });
    container.appendChild(pre);
  }

  function jumpToHash() {
    if (!location.hash) return;
    var target = document.getElementById(decodeURIComponent(location.hash.slice(1)));
    if (target) target.scrollIntoView();
  }

  function materialIdFromPath() {
    var m = location.pathname.match(/\/materials\/(\d+)\/preview/);
    return m ? m[1] : null;
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.getElementById("logout-btn").addEventListener("click", function () {
      api.clearToken();
      location.assign("/login");
    });

    var id = materialIdFromPath();
    if (!id) {
      showMessage("error", "无效的预览地址");
      return;
    }

    api
      .authFetch("/api/materials/" + id + "/content")
      .then(function (response) {
        if (!response.ok) throw new Error("load failed");
        return response.json();
      })
      .then(function (data) {
        document.getElementById("material-title").textContent = data.original_name;
        var container = document.getElementById("content");
        if (data.ext === "md") {
          renderMarkdown(container, data.content);
        } else {
          renderTxt(container, data.content);
        }
        jumpToHash();
      })
      .catch(function () {
        showMessage("error", "内容加载失败，请确认有权访问该材料");
      });
  });
})();
