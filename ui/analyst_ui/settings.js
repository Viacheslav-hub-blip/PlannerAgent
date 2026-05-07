/**
 * Страница настроек: базовый URL API.
 */

function init() {
  $("apiBaseInput").value = getApiBase();
  $("apiSettingsForm").addEventListener("submit", (event) => {
    event.preventDefault();
    const value = $("apiBaseInput").value.trim() || "/api/v1";
    setApiBase(value);
    setStatus("statusBar", "Сохранено. Новые запросы пойдут на этот адрес.", "success");
  });
}

init();
