/* Dark / light mode toggle; persisted in localStorage. */

(function () {
  const btn = document.getElementById("theme-toggle");

  function render() {
    btn.textContent = document.documentElement.dataset.theme === "dark" ? "☀" : "☾";
  }

  btn.addEventListener("click", () => {
    const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    localStorage.setItem("theme", next);
    render();
  });

  render();
})();
