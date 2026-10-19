// Open the chosen course as soon as it is picked.
// Without JavaScript the "Show" button next to the list does the same job.
document.documentElement.classList.add("js");
document.querySelectorAll("form[data-autosubmit] select").forEach(function (select) {
  select.addEventListener("change", function () {
    select.form.submit();
  });
});

// Remember the last board opened on this device, and offer it on the home page.
// Stored only in this browser; storage can be blocked (private mode), so failures are ignored.
(function () {
  var KEY = "hnu-board:last";
  var board = document.querySelector("[data-remember-board]");
  try {
    if (board) {
      localStorage.setItem(KEY, JSON.stringify({
        query: board.dataset.rememberBoard,
        label: board.dataset.rememberLabel
      }));
      return;
    }
    var resume = document.querySelector("[data-resume]");
    var saved = JSON.parse(localStorage.getItem(KEY) || "null");
    if (resume && saved && /^\?year=\d&program=[\w-]+$/.test(saved.query)) {
      var link = resume.querySelector("a");
      link.href = saved.query;
      link.textContent = "Continue to " + saved.label + " →";
      resume.hidden = false;
    }
  } catch (e) {
    // no storage: the picker still works
  }
})();
