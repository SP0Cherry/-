/* Central API helper: token storage, Bearer injection, 401 handling. */
(function () {
  "use strict";

  var TOKEN_KEY = "campusclaw_token";

  function getToken() {
    return localStorage.getItem(TOKEN_KEY);
  }
  function setToken(token) {
    localStorage.setItem(TOKEN_KEY, token);
  }
  function clearToken() {
    localStorage.removeItem(TOKEN_KEY);
  }

  /* fetch wrapper that attaches the bearer token.
     opts.skipAuthRedirect = true prevents the global 401 -> /login jump
     (used by the login page itself). */
  function authFetch(path, opts) {
    opts = opts || {};
    var headers = new Headers(opts.headers || {});
    var token = getToken();
    if (token) headers.set("Authorization", "Bearer " + token);

    return fetch(path, {
      method: opts.method || "GET",
      headers: headers,
      body: opts.body,
      credentials: "same-origin",
      signal: opts.signal
    }).then(function (response) {
      if (
        response.status === 401 &&
        !opts.skipAuthRedirect &&
        !location.pathname.endsWith("/login")
      ) {
        clearToken();
        location.assign("/login");
      }
      return response;
    });
  }

  function jsonRequest(path, method, body) {
    return authFetch(path, {
      method: method,
      headers: { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body)
    }).then(function (response) {
      return response.json().catch(function () { return null; }).then(function (data) {
        return { ok: response.ok, status: response.status, data: data };
      });
    });
  }

  window.CampusClaw = {
    getToken: getToken,
    setToken: setToken,
    clearToken: clearToken,
    authFetch: authFetch,
    jsonRequest: jsonRequest
  };
})();
