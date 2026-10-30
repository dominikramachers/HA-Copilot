// Demo-Rahmen: bettet die App wie der Supervisor-Ingress per iframe (gleiche Herkunft) ein.
class HaCopilotPanel extends HTMLElement {
  set hass(h) { this._hass = h; }
  set narrow(v) { this._narrow = v; }
  set route(v) {}
  set panel(v) {}
  connectedCallback() {
    if (this.firstChild) return;
    this.style.cssText = "display:block;height:100%;";
    const f = document.createElement("iframe");
    f.src = "/api/hassio_ingress/demo/";
    f.style.cssText = "border:0;width:100%;height:100%;display:block;";
    f.allow = "clipboard-write";
    this.appendChild(f);
  }
}
customElements.define("ha-copilot-panel", HaCopilotPanel);
