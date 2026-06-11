/* 论文雷达 —— 客户端筛选与倒计时(无依赖) */
(function () {
  "use strict";

  var tabs = document.querySelectorAll(".field-tab");
  var cards = document.querySelectorAll(".paper-card");
  var searchInput = document.getElementById("search");
  var visibleCount = document.getElementById("visible-count");
  var currentField = "all";

  function applyFilter() {
    var q = (searchInput.value || "").trim().toLowerCase();
    var shown = 0;
    cards.forEach(function (card) {
      var fieldOk = currentField === "all" ||
        (" " + card.dataset.fields + " ").indexOf(" " + currentField + " ") !== -1;
      var searchOk = !q || card.dataset.search.indexOf(q) !== -1;
      var show = fieldOk && searchOk;
      card.classList.toggle("is-hidden", !show);
      if (show) shown++;
    });
    visibleCount.textContent = "显示 " + shown + " 篇";
  }

  tabs.forEach(function (tab) {
    tab.addEventListener("click", function () {
      tabs.forEach(function (t) { t.classList.remove("is-active"); });
      tab.classList.add("is-active");
      currentField = tab.dataset.field;
      applyFilter();
      window.scrollTo({ top: 0, behavior: "smooth" });
    });
  });

  var debounce;
  searchInput.addEventListener("input", function () {
    clearTimeout(debounce);
    debounce = setTimeout(applyFilter, 120);
  });

  /* 到下一次 06:00 更新的倒计时(按浏览器本地时间近似展示) */
  var countdownEl = document.getElementById("countdown");
  function tick() {
    var now = new Date();
    var target = new Date(now);
    target.setHours(UPDATE_HOUR, UPDATE_MINUTE, 0, 0);
    if (target <= now) target.setDate(target.getDate() + 1);
    var s = Math.floor((target - now) / 1000);
    var h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
    countdownEl.textContent =
      String(h).padStart(2, "0") + ":" + String(m).padStart(2, "0") + ":" + String(sec).padStart(2, "0");
  }
  tick();
  setInterval(tick, 1000);

  applyFilter();
})();
