/* Same-origin Swagger UI shell. No external resources, no token persistence:
   the user pastes a bearer token into the Authorize dialog for this session. */
(function () {
  "use strict";

  window.addEventListener("load", function () {
    window.ui = SwaggerUIBundle({
      url: "/api/openapi.json",
      dom_id: "#swagger-ui",
      presets: [SwaggerUIBundle.presets.apis, SwaggerUIStandalonePreset],
      layout: "StandaloneLayout",
      deepLinking: true,
      persistAuthorization: false,
      validatorUrl: null
    });
  });
})();
