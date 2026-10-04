// Keyboard reference and other undocumented features. Everything here is optional: the manual
// reads the same without this file. It only navigates, scrolls, and prints facts already on
// the page; it sends nothing anywhere and stores nothing.
(function () {
  "use strict";

  var KONAMI = [
    "ArrowUp", "ArrowUp", "ArrowDown", "ArrowDown",
    "ArrowLeft", "ArrowRight", "ArrowLeft", "ArrowRight", "b", "a",
  ];

  function build() {
    var meta = document.querySelector('meta[name="sysops-pub-build"]');
    var parts = meta ? meta.getAttribute("content").split(" ") : [];
    return { commit: parts[0] || "", version: parts[1] || "", date: parts[2] || "" };
  }

  function toast(text) {
    var node = document.querySelector(".toast");
    if (!node) {
      return;
    }
    node.textContent = text;
    node.hidden = false;
    window.clearTimeout(toast.timer);
    toast.timer = window.setTimeout(function () {
      node.hidden = true;
    }, 4200);
  }

  // Jump keys read the thumb index already on the page, so they cannot drift from the manual.
  function jump(key) {
    if (key === "e") {
      return "/errata/";
    }
    var wanted = key === "c" ? "cmd" : key.toLowerCase();
    var tabs = document.querySelectorAll(".thumbs .tab");
    for (var index = 0; index < tabs.length; index += 1) {
      var label = tabs[index].querySelector(".tab-key");
      if (label && label.textContent.trim().toLowerCase() === wanted) {
        return tabs[index].getAttribute("href");
      }
    }
    return null;
  }

  function follow(rel) {
    var link = document.querySelector('a[rel="' + rel + '"]');
    if (link) {
      window.location.href = link.href;
    }
  }

  document.addEventListener("DOMContentLoaded", function () {
    var info = build();
    var dialog = document.querySelector(".keys");
    var hint = document.querySelector(".hint");
    var last = "";
    var konami = 0;

    if (hint) {
      hint.hidden = false;
    }
    document.querySelectorAll(".missing-path").forEach(function (node) {
      node.textContent = window.location.pathname.replace(/^\/|\/$/g, "") || "/";
    });
    if (window.console && info.commit) {
      window.console.log(
        "%csysops_pub " + info.version + "%c\ncommit " + info.commit + " · " + info.date +
          "\nBuilt by tools/build_site.py from the tracked documents." +
          "\nNothing on this site is hand-copied; read the source and verify it yourself." +
          "\n" + "https://github.com/sparklbarff/sysops_pub/tree/" + info.commit,
        "font: 800 14px sans-serif",
        "font: 12px monospace"
      );
    }
    if (dialog) {
      dialog.querySelector(".close").addEventListener("click", function () {
        dialog.close();
      });
    }

    document.addEventListener("keydown", function (event) {
      if (event.metaKey || event.ctrlKey || event.altKey) {
        return;
      }
      var target = event.target;
      if (target && (target.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName))) {
        return;
      }
      var key = event.key;

      konami = key === KONAMI[konami] ? konami + 1 : key === KONAMI[0] ? 1 : 0;
      if (konami === KONAMI.length) {
        konami = 0;
        toast("No cheat codes. Verify independently.");
        return;
      }
      if (konami > 8) {
        return;
      }
      if (dialog && dialog.open) {
        if (key === "?" || key === "Escape") {
          dialog.close();
          event.preventDefault();
        }
        return;
      }
      if (key === "?") {
        if (dialog) {
          dialog.showModal();
          event.preventDefault();
        }
      } else if (key === "j" || key === "k") {
        window.scrollBy({ top: key === "j" ? 72 : -72 });
      } else if (key === "g" && last === "g") {
        window.scrollTo({ top: 0 });
        key = "";
      } else if (key === "G") {
        window.scrollTo({ top: document.body.scrollHeight });
      } else if (key === "n") {
        follow("next");
      } else if (key === "p") {
        follow("prev");
      } else if (key === "t") {
        var button = document.querySelector(".theme");
        if (button) {
          button.click();
        }
      } else if (/^[0-9abce]$/.test(key) && jump(key)) {
        window.location.href = jump(key);
      }
      last = key;
    });
  });
})();
