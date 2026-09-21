import { app } from "/scripts/app.js";
import { ComfyWidgets } from "/scripts/widgets.js";

// Scope this extension to the inference Studio. Existing DreamFace training nodes
// and every other extension keep their own appearance and execution hooks.
const STUDIO_NODES = new Set([
    "DP_LoadPhoto", "DP_ReferenceStudio", "DP_IdentityEncoder", "DP_SceneStudio", "DP_SwapPrompt",
    "DP_KleinConditioning", "DP_DreamSwap", "DP_SeamFinish", "DP_ReviewBoard",
]);
const statusWidgets = new WeakMap();

function readableReport(text) {
    try {
        const report = JSON.parse(text);
        const lines = [];
        if (report.shape) lines.push(`Bilde: ${report.shape[1]} × ${report.shape[0]} px`);
        if (report.mask_channel) lines.push(`Maskekanal: ${report.mask_channel} · hvitt kan endres`);
        if (report.reference_count) lines.push(`Identitetsreferanser: ${report.reference_count}`);
        if (report.reference_order) lines.push(`Bilderekkefølge: ${report.reference_order.join(" → ")}`);
        if (report.scene_mode) lines.push(`Scenereferanse: ${report.scene_mode}`);
        if (report.engine) lines.push(`Klein 9B · ${report.engine} · ${report.steps} steg · seed ${report.seed}`);
        if (report.elapsed_seconds !== undefined) lines.push(`Sampling: ${report.elapsed_seconds.toFixed(1)} s`);
        if (report.outside_mask_exact !== undefined) {
            lines.push(report.outside_mask_exact ? "Beskyttede piksler: uendret" : "FEIL: piksler utenfor masken er endret");
            lines.push("Vurder selv identitet, hår, uttrykk og realisme i resultatet.");
        }
        if (report.prompt) lines.push(report.prompt);
        return lines.length ? lines.join("\n") : text.slice(0, 24000);
    } catch {
        return text.slice(0, 24000);
    }
}

function addStatus(node) {
    if (statusWidgets.has(node)) return statusWidgets.get(node);
    const { widget } = ComfyWidgets.STRING(
        node, "studio_status", ["STRING", { multiline: true, default: "Klar · rapport vises etter kjøring" }], app,
    );
    widget.options ??= {};
    widget.options.serialize = false;
    widget.computeSize = (width) => [width, 112];
    if (widget.inputEl) {
        widget.inputEl.readOnly = true;
        widget.inputEl.setAttribute("aria-label", "DreamPage execution report, read only");
        widget.inputEl.style.fontSize = "11px";
        widget.inputEl.style.lineHeight = "1.4";
        widget.inputEl.style.color = "#b7d7d1";
        widget.inputEl.style.backgroundColor = "#142329";
    }
    statusWidgets.set(node, widget);
    return widget;
}

app.registerExtension({
    name: "DreamPage.KleinStudio",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (!STUDIO_NODES.has(nodeData.name) || nodeData.category !== "DreamPage/Studio") return;
        const previousCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function (...args) {
            const result = previousCreated?.apply(this, args);
            this.color = "#244b4b";
            this.bgcolor = "#182b30";
            addStatus(this);
            const minimum = this.computeSize();
            this.setSize([Math.max(this.size[0], 360, minimum[0]), Math.max(this.size[1], minimum[1])]);
            return result;
        };
        const previousExecuted = nodeType.prototype.onExecuted;
        nodeType.prototype.onExecuted = function (message, ...args) {
            const result = previousExecuted?.call(this, message, ...args);
            const report = message?.dp_report?.[0];
            if (typeof report === "string") {
                // The built-in text widget displays data only: no HTML/DOM injection.
                addStatus(this).value = readableReport(report);
                this.setDirtyCanvas(true, true);
            }
            return result;
        };
    },
});
