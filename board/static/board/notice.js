// "What's new" banner: hide it once closed on this device, until a newer notice appears.
(function () {
  var notice = document.querySelector("[data-notice]");
  if (!notice) return;
  var KEY = "hnu-board:notice-closed";
  try {
    if (localStorage.getItem(KEY) === notice.dataset.notice) {
      notice.remove();
      return;
    }
  } catch (e) {}
  var close = notice.querySelector("[data-notice-close]");
  close.hidden = false; // the button only works with JavaScript, so show it only then
  close.addEventListener("click", function () {
    notice.remove();
    try { localStorage.setItem(KEY, notice.dataset.notice); } catch (e) {}
  });
})();
