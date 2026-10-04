// Light and dark modes. The page follows the system setting until the reader picks one with the
// switch in the running header; that choice is remembered in this browser only. This file is the
// site's only script. Without it the page still follows the system setting.
(function () {
  "use strict";
  var KEY = "sysops_pub.theme";
  var root = document.documentElement;
  var stored = null;
  try {
    stored = window.localStorage.getItem(KEY);
  } catch (error) {
    stored = null;
  }
  if (stored === "light" || stored === "dark") {
    root.setAttribute("data-theme", stored);
  }

  function current() {
    var chosen = root.getAttribute("data-theme");
    if (chosen) {
      return chosen;
    }
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }

  function label(button) {
    var next = current() === "dark" ? "light" : "dark";
    button.textContent = next === "dark" ? "Dark" : "Light";
    button.setAttribute("aria-label", "Switch to " + next + " mode");
  }

  document.addEventListener("DOMContentLoaded", function () {
    var button = document.querySelector(".theme");
    if (!button) {
      return;
    }
    button.hidden = false;
    label(button);
    button.addEventListener("click", function () {
      var next = current() === "dark" ? "light" : "dark";
      root.setAttribute("data-theme", next);
      try {
        window.localStorage.setItem(KEY, next);
      } catch (error) {
        // Private browsing can refuse storage; the switch still works for this page.
      }
      label(button);
    });
    window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", function () {
      label(button);
    });
  });
})();
