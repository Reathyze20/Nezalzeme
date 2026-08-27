/**
 * Nastaví třídu .dark na <html> ještě před prvním vykreslením, aby motiv
 * nebliknul. Čte uloženou volbu, jinak respektuje systémové nastavení.
 */
export function ThemeScript() {
  const script = `
    try {
      var ulozeno = localStorage.getItem("motiv");
      var tmave = ulozeno ? ulozeno === "tmavy" : window.matchMedia("(prefers-color-scheme: dark)").matches;
      document.documentElement.classList.toggle("dark", tmave);
    } catch (e) {}
  `;
  // eslint-disable-next-line react/no-danger
  return <script dangerouslySetInnerHTML={{ __html: script }} />;
}
