/* ArchitectHire Studio — interaction layer.
 * Loaded on every admin page via UNFOLD["SCRIPTS"]. No dependencies: Unfold already
 * ships Alpine and htmx, and this file must stay collectstatic-clean under
 * CompressedManifestStaticFilesStorage. */
(function () {
  "use strict";

  var DENSITY_KEY = "studio:density";

  /* Row density is a per-user preference, not a per-page one: the owner works
   * through 1,800-row copy-block lists and wants that choice to persist. */
  function applyDensity(value) {
    document.documentElement.setAttribute("data-studio-density", value);
  }

  function initDensity() {
    var stored = null;
    try {
      stored = window.localStorage.getItem(DENSITY_KEY);
    } catch (e) {
      /* Private-mode / disabled storage: fall back to the default silently. */
    }
    applyDensity(stored === "compact" ? "compact" : "comfortable");

    document.addEventListener("click", function (event) {
      var toggle = event.target.closest("[data-studio-density-toggle]");
      if (!toggle) return;
      event.preventDefault();
      var next =
        document.documentElement.getAttribute("data-studio-density") === "compact"
          ? "comfortable"
          : "compact";
      applyDensity(next);
      try {
        window.localStorage.setItem(DENSITY_KEY, next);
      } catch (e) {
        /* Preference simply does not persist. */
      }
    });
  }

  /* ---- Media library: upload into a slot without leaving the grid ---------
   * MediaAsset rows are a fixed inventory, so the only action a tile needs is
   * "put an image in this one". A full page reload per upload would make filling
   * 47 slots miserable. */

  function csrfToken() {
    var match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]*)/);
    return match ? decodeURIComponent(match[1]) : "";
  }

  function uploadToSlot(tile, file, uploadUrl) {
    var preview = tile.querySelector("[data-media-preview]");
    var placeholder = tile.querySelector("[data-media-placeholder]");
    var progress = tile.querySelector("[data-media-progress]");
    var error = tile.querySelector("[data-media-error]");

    error.hidden = true;
    progress.hidden = false;

    var payload = new FormData();
    payload.append("slot_key", tile.dataset.slotKey);
    payload.append("image", file);

    fetch(uploadUrl, {
      method: "POST",
      body: payload,
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken() },
    })
      .then(function (response) {
        return response.json().then(function (data) {
          if (!response.ok) throw new Error(data.error || "Upload failed.");
          return data;
        });
      })
      .then(function (data) {
        preview.src = data.url;
        preview.alt = data.alt_text || "";
        preview.hidden = false;
        placeholder.hidden = true;
        tile.classList.remove("studio-tile--empty");
      })
      .catch(function (err) {
        error.textContent = err.message;
        error.hidden = false;
      })
      .finally(function () {
        progress.hidden = true;
        tile.classList.remove("studio-tile--dropping");
      });
  }

  function initMediaGrid() {
    var grid = document.querySelector("[data-media-grid]");
    if (!grid) return;
    var uploadUrl = grid.dataset.uploadUrl;

    grid.addEventListener("change", function (event) {
      var input = event.target.closest("[data-media-input]");
      if (!input || !input.files.length) return;
      uploadToSlot(input.closest("[data-media-tile]"), input.files[0], uploadUrl);
      input.value = "";
    });

    ["dragenter", "dragover"].forEach(function (name) {
      grid.addEventListener(name, function (event) {
        var tile = event.target.closest("[data-media-tile]");
        if (!tile) return;
        event.preventDefault();
        tile.classList.add("studio-tile--dropping");
      });
    });

    grid.addEventListener("dragleave", function (event) {
      var tile = event.target.closest("[data-media-tile]");
      if (tile && !tile.contains(event.relatedTarget)) {
        tile.classList.remove("studio-tile--dropping");
      }
    });

    grid.addEventListener("drop", function (event) {
      var tile = event.target.closest("[data-media-tile]");
      if (!tile) return;
      event.preventDefault();
      var files = event.dataTransfer && event.dataTransfer.files;
      if (files && files.length) uploadToSlot(tile, files[0], uploadUrl);
      else tile.classList.remove("studio-tile--dropping");
    });
  }

  function init() {
    initDensity();
    initMediaGrid();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
