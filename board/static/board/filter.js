// Open the chosen course as soon as it is picked.
// Without JavaScript the "Show" button next to the list does the same job.
document.documentElement.classList.add("js");
document.querySelectorAll("form[data-autosubmit] select").forEach(function (select) {
  select.addEventListener("change", function () {
    select.form.submit();
  });
});
