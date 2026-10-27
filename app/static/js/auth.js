/* Login and register page behavior. Renders all server strings via
   textContent only (never innerHTML) to avoid XSS. */
(function () {
  "use strict";

  var api = window.CampusClaw;

  function showMessage(kind, text) {
    var el = document.getElementById("message");
    el.className = "message " + kind;
    el.textContent = text;
  }

  function initLogin() {
    var form = document.getElementById("login-form");
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      var username = document.getElementById("username").value;
      var password = document.getElementById("password").value;
      showMessage("muted", "");
      document.querySelector("#message").className = "message";
      api
        .jsonRequest("/api/auth/login", "POST", {
          username: username,
          password: password
        })
        .then(function (result) {
          if (result.ok && result.data && result.data.access_token) {
            api.setToken(result.data.access_token);
            location.assign("/");
          } else {
            var msg =
              (result.data && (result.data.message || result.data.error)) ||
              "登录失败";
            showMessage("error", msg);
          }
        })
        .catch(function () {
          showMessage("error", "网络错误，请稍后再试");
        });
    });
  }

  function initRegister() {
    var select = document.getElementById("class_id");
    api
      .authFetch("/api/auth/classes", { skipAuthRedirect: true })
      .then(function (response) {
        return response.ok ? response.json() : null;
      })
      .then(function (data) {
        select.textContent = "";
        var placeholder = document.createElement("option");
        placeholder.value = "";
        placeholder.textContent = "请选择班级";
        select.appendChild(placeholder);
        (data && data.items ? data.items : []).forEach(function (c) {
          var opt = document.createElement("option");
          opt.value = String(c.id);
          opt.textContent = c.name;
          select.appendChild(opt);
        });
      })
      .catch(function () {
        showMessage("error", "班级列表加载失败，请刷新重试");
      });

    var form = document.getElementById("register-form");
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      var body = {
        username: document.getElementById("username").value,
        password: document.getElementById("password").value,
        role: document.getElementById("role").value,
        class_id: Number(document.getElementById("class_id").value)
      };
      api
        .jsonRequest("/api/auth/register", "POST", body)
        .then(function (result) {
          if (result.ok) {
            location.assign("/login");
          } else {
            var messages =
              (result.data && result.data.messages) ||
              [(result.data && result.data.message) || "注册失败"];
            showMessage("error", messages.join("；"));
          }
        })
        .catch(function () {
          showMessage("error", "网络错误，请稍后再试");
        });
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    var page = document.body.getAttribute("data-page");
    if (page === "login") initLogin();
    else if (page === "register") initRegister();
  });
})();
