/* Report tools — studio panel contributed by the report distribution module
   (declared in module.yaml provides.studio_panels; served by core studio at
   /api/panels/report-tools/entry). Core studio knows nothing about this
   file's contents: the content-audit action lives HERE, and its backend
   invocation goes through the generic run-checker action, which resolves
   the checker through the distribution-module registry. */
(function () {
  "use strict";
  if (!window.RigorloomStudio) return;
  window.RigorloomStudio.register("report-tools", function (el, ctx) {
    if (!ctx.actionsEnabled) {
      el.innerHTML = '<div class="empty">Read-only mode — set STUDIO_ALLOW_ACTIONS=1 to run report tools.</div>';
      return;
    }
    el.innerHTML = '<div class="actions"><button class="button" type="button" data-checker="content_audit">Run content audit</button></div>';
    el.querySelector("button").onclick = function () {
      ctx.runAction("run-checker", null, { checker: "content_audit" });
    };
  });
})();
