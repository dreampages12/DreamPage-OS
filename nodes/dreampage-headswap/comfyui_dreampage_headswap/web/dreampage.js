import { app } from "/scripts/app.js";
import { ComfyWidgets } from "/scripts/widgets.js";

// Scope this extension to the inference Studio. Existing DreamFace training nodes
// and every other extension keep their own appearance and execution hooks.
const STUDIO_NODES = new Set([
    "DP_LoadPhoto", "DP_ReferenceStudio", "DP_IdentityEncoder", "DP_SceneStudio", "DP_SwapPrompt",
    "DP_KleinConditioning", "DP_DreamSwap", "DP_SeamFinish", "DP_ReviewBoard",
]);
const statusWidgets = new WeakMap();

function addStatus(node) {
    if (statusWidgets.has(node)) return statusWidgets.get(node);
    const { widget } = ComfyWidgets.STRING(
        node, "studio_status", ["STRING", { multiline: true, default: "Ready · report appears after execution" }], app,
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
                addStatus(this).value = report.slice(0, 24000);
                this.setDirtyCanvas(true, true);
            }
            return result;
        };
    },
});
