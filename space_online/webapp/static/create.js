(() => {
  "use strict";

  const { names } = JSON.parse(document.getElementById("creation-data").textContent);

  document.querySelectorAll("[data-random-name]").forEach((button) => {
    button.addEventListener("click", () => {
      document.getElementById(button.dataset.randomName).value = names[Math.floor(Math.random() * names.length)];
    });
  });

  const chooser = document.getElementById("lobby-chooser");
  const panels = document.querySelectorAll("[data-lobby-panel]");
  const showPanel = (name) => {
    chooser.classList.toggle("hidden", name !== null);
    panels.forEach((panel) => panel.classList.toggle("hidden", panel.dataset.lobbyPanel !== name));
  };
  document.querySelectorAll("[data-lobby-choose]").forEach((button) => {
    button.addEventListener("click", () => showPanel(button.dataset.lobbyChoose));
  });
  document.querySelectorAll("[data-lobby-back]").forEach((button) => {
    button.addEventListener("click", () => showPanel(null));
  });

  const mode = document.getElementById("round-mode");
  if (mode) {
    const description = document.getElementById("round-mode-description");
    const showDescription = () => {
      description.textContent = mode.selectedOptions[0].dataset.description;
    };
    mode.addEventListener("change", showDescription);
    showDescription();
  }
})();
