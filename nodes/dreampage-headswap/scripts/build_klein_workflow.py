"""Build the editable Klein Studio UI graph and matching API graph; never queue a job.

Node widgets and connection indices are derived from the real schemas. The running
ComfyUI server supplies core node metadata; DreamPage metadata comes from local code.
"""
from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path
import sys
import urllib.request
import uuid


ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "src"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
if (ROOT.parent / "folder_paths.py").is_file() and str(ROOT.parent) not in sys.path:
    sys.path.append(str(ROOT.parent))

WIDGET_TYPES = {"INT", "FLOAT", "STRING", "BOOLEAN"}


def get_schemas(server: str) -> dict:
    with urllib.request.urlopen(server.rstrip("/") + "/object_info", timeout=20) as response:
        schemas = json.load(response)
    native = importlib.import_module("comfyui_dreampage_headswap.native_nodes")
    mappings = getattr(native, "NODE_CLASS_MAPPINGS", None)
    if mappings is None:
        mappings = native.NATIVE_NODE_CLASS_MAPPINGS
    for name, node in mappings.items():
        schemas[name] = {
            "input": node.INPUT_TYPES(),
            "output": list(node.RETURN_TYPES),
            "output_name": list(getattr(node, "RETURN_NAMES", node.RETURN_TYPES)),
            "output_node": bool(getattr(node, "OUTPUT_NODE", False)),
        }
    return schemas


class Graph:
    def __init__(self, schemas: dict):
        self.schemas = schemas
        self.nodes: list[dict] = []
        self.links: list[list] = []
        self.groups: list[dict] = []
        self.api: dict[str, dict] = {}
        self.by_key: dict[str, dict] = {}

    def node(self, key, kind, title, pos, size, values=None, color="#244b4b"):
        schema = self.schemas[kind]
        values = values or {}
        nid = len(self.nodes) + 1
        inputs, widgets, api_inputs = [], [], {}
        for section in ("required", "optional"):
            for name, spec in schema["input"].get(section, {}).items():
                dtype = spec[0]
                options = spec[1] if len(spec) > 1 else {}
                is_widget = (isinstance(dtype, (list, tuple)) or dtype in WIDGET_TYPES) and not options.get("forceInput")
                item = {"name": name, "type": "COMBO" if isinstance(dtype, (list, tuple)) else dtype, "link": None}
                if is_widget:
                    value = values.get(name, options.get("default"))
                    if value is None:
                        value = dtype[0] if isinstance(dtype, (list, tuple)) else {"STRING": "", "BOOLEAN": False, "INT": 0, "FLOAT": 0.0}[dtype]
                    item["widget"] = {"name": name}
                    widgets.append(value)
                    api_inputs[name] = value
                    if options.get("control_after_generate"):
                        widgets.append("fixed")
                inputs.append(item)
        if kind in ("LoadImage", "LoadImageMask", "DP_LoadPhoto"):
            inputs.append({"name": "upload", "type": "IMAGEUPLOAD", "widget": {"name": "upload"}, "link": None})
            widgets.append("image")
        outputs = [{"name": name, "type": dtype, "links": None, "slot_index": i}
                   for i, (name, dtype) in enumerate(zip(schema.get("output_name", schema["output"]), schema["output"]))]
        node = {"id": nid, "type": kind, "pos": list(pos), "size": list(size), "flags": {},
                "order": nid - 1, "mode": 0, "inputs": inputs, "outputs": outputs,
                "title": title, "properties": {"Node name for S&R": kind},
                "widgets_values": widgets, "color": color, "bgcolor": "#182b30"}
        self.nodes.append(node)
        self.by_key[key] = node
        self.api[str(nid)] = {"class_type": kind, "inputs": api_inputs, "_meta": {"title": title}}
        return node

    def note(self, title, text, pos, size):
        nid = len(self.nodes) + 1
        self.nodes.append({"id": nid, "type": "Note", "pos": list(pos), "size": list(size),
                           "flags": {}, "order": nid - 1, "mode": 0, "inputs": [], "outputs": [],
                           "title": title, "properties": {}, "widgets_values": [text],
                           "color": "#24343d", "bgcolor": "#17252c"})

    def link(self, source, source_slot, target, name):
        origin, destination = self.by_key[source], self.by_key[target]
        target_slot = next(i for i, v in enumerate(destination["inputs"]) if v["name"] == name)
        input_ = destination["inputs"][target_slot]
        output = origin["outputs"][source_slot]
        if output["type"] != input_["type"]:
            raise ValueError(f"Type mismatch: {source}:{output['type']} -> {target}.{name}:{input_['type']}")
        if input_["link"] is not None:
            raise ValueError(f"Input already wired: {target}.{name}")
        lid = len(self.links) + 1
        self.links.append([lid, origin["id"], source_slot, destination["id"], target_slot, output["type"]])
        input_["link"] = lid
        if output["links"] is None:
            output["links"] = []
        output["links"].append(lid)
        self.api[str(destination["id"])]["inputs"][name] = [str(origin["id"]), source_slot]

    def group(self, title, bounding, color):
        self.groups.append({"id": len(self.groups) + 1, "title": title,
                            "bounding": list(bounding), "color": color,
                            "font_size": 24, "flags": {}})

    def validate(self):
        for node in self.nodes:
            if node["type"] == "Note":
                continue
            api = self.api[str(node["id"])]["inputs"]
            required = self.schemas[node["type"]]["input"].get("required", {})
            missing = set(required) - set(api)
            if missing:
                raise ValueError(f"Missing required inputs for {node['type']}: {sorted(missing)}")
        # Check every native node reaches a real output, rather than merely appearing on canvas.
        ancestors = set()
        stack = [nid for nid, item in self.api.items() if self.schemas[item["class_type"]].get("output_node")]
        while stack:
            nid = stack.pop()
            if nid in ancestors:
                continue
            ancestors.add(nid)
            stack.extend(v[0] for v in self.api[nid]["inputs"].values()
                         if isinstance(v, list) and len(v) == 2 and str(v[0]) in self.api)
        for nid, node in self.api.items():
            if node["class_type"].startswith("DP_") and nid not in ancestors:
                raise ValueError(f"Native node disconnected from outputs: {node['class_type']}")
        # Nodes may share wires but must not overlap their neighbours or instructional notes.
        for i, left in enumerate(self.nodes):
            lx, ly = left["pos"]; lw, lh = left["size"]
            for right in self.nodes[i + 1:]:
                rx, ry = right["pos"]; rw, rh = right["size"]
                if lx < rx + rw and rx < lx + lw and ly - 30 < ry + rh and ry - 30 < ly + lh:
                    raise ValueError(f"Nodes overlap: {left['title']} / {right['title']}")

    def workflow(self):
        return {"id": str(uuid.uuid5(uuid.NAMESPACE_URL, "dreampage:klein9b-studio:v1")),
                "revision": 1, "last_node_id": len(self.nodes), "last_link_id": len(self.links),
                "nodes": self.nodes, "links": self.links, "groups": self.groups,
                "config": {}, "extra": {"ds": {"scale": 0.33, "offset": [80, 120]},
                                           "dreampage": {"edition": "Klein 9B Studio", "training": False,
                                                         "trained_identity_encoder": False, "lora_loaded": False}},
                "version": 0.4}


def build(schemas):
    g = Graph(schemas)
    g.group("01  /  EXISTING KLEIN 9B", (0, 0, 720, 1160), "#34566b")
    g.group("02  /  YOUR THREE INPUTS", (780, 0, 1320, 1160), "#43655a")
    g.group("03  /  IDENTITY REFERENCES", (2160, 0, 1200, 1160), "#39746c")
    g.group("04  /  SCENE & WRITE AREA", (0, 1240, 1040, 1590), "#577455")
    g.group("05  /  DIRECT & GENERATE", (1120, 1240, 1040, 1590), "#526186")
    g.group("06  /  FINISH & REVIEW", (2240, 1240, 1280, 1590), "#8a7150")

    g.note("DreamPage  /  Klein 9B Studio", "START HERE\nUse your existing Klein 9B, Qwen3-8B and FLUX.2 VAE.\nChoose the three images in group 02, then run.\n4 steps · fixed seed · native sampler · no LoRA loaded.\nThis workflow performs inference only.", (30, 70), (660, 170))
    g.node("model", "UNETLoader", "Klein 9B  /  existing model", (30, 310), (660, 150),
           {"unet_name": "flux-2-klein-9b.safetensors", "weight_dtype": "default"}, "#2f4c63")
    g.node("clip", "CLIPLoaderGGUF", "Qwen3-8B  /  text encoder", (30, 530), (660, 150),
           {"clip_name": "Qwen3-8B-Q8_0.gguf", "type": "flux2"}, "#2f4c63")
    g.node("vae", "VAELoader", "FLUX.2  /  image encoder + decoder", (30, 750), (660, 130),
           {"vae_name": "flux2-vae.safetensors"}, "#2f4c63")
    g.note("Later  /  your trained LoRA", "When a compatible 9B LoRA is ready, insert Load LoRA (Model Only) between the model above and DP DreamSwap.\nThe current workflow loads no LoRA.", (30, 970), (660, 130))

    g.note("One person  +  one scene  +  its headmask", "PERSON: sharp portrait with the full head, hair and ears visible.\nSCENE: the original image to edit. MASK: the matching headmask; keep channel = red.\nWhite is editable. Black stays exactly as it was. Replace these example selections with your own test case.", (810, 70), (1260, 170))
    g.node("person", "DP_LoadPhoto", "A  /  person to insert", (810, 310), (390, 660),
           {"image": "26063001.jpg", "mask_channel": "red"}, "#355e51")
    g.node("template", "DP_LoadPhoto", "B  /  original scene", (1245, 310), (390, 660),
           {"image": "forside(dyreparken).jpg", "mask_channel": "red"}, "#355e51")
    g.node("mask", "DP_LoadPhoto", "C  /  scene headmask · RED", (1680, 310), (390, 660),
           {"image": "forside-headmask(dyreparken).png", "mask_channel": "red"}, "#355e51")

    g.note("Identity  /  inspect the actual reference", "The preview shows what the image encoder receives. Aspect ratio is preserved.\nFor a wide source photo, connect a source headmask to isolate the full head.\nOptional view_2 and view_3 accept other photos of the SAME person.", (2190, 70), (1140, 170))
    g.node("references", "DP_ReferenceStudio", "Prepare identity views", (2190, 310), (540, 440),
           {"resolution": 768, "context": 1.25, "background_strength": 0.0})
    g.node("reference_preview", "PreviewImage", "Prepared identity  /  what Klein sees", (2790, 310), (540, 560))
    g.node("identity", "DP_IdentityEncoder", "Identity Encoder  /  pretrained VAE", (2190, 840), (540, 230))
    g.note("Encoder status", "Visual reference conditioning works with the existing pretrained VAE. The specialized DreamFace encoder has not been trained yet.", (2790, 970), (540, 140))
    g.link("person", 0, "references", "person")
    g.link("references", 1, "reference_preview", "images")
    g.link("references", 0, "identity", "references")
    g.link("vae", 0, "identity", "vae")

    g.note("Keep the headmask aligned", "Inspect the teal overlay and cropped scene. Context and expansion help generation; they never enlarge the final write area.\nStart with the supplied settings, then compare one change at a time.", (30, 1320), (980, 130))
    g.node("scene", "DP_SceneStudio", "Scene Studio  /  crop + mask authority", (30, 1530), (480, 620),
           {"resolution": 1024, "context": 1.5, "expand": 0, "feather": 8.0,
            "edge_protection": 0.65, "scene_mode": "original"})
    g.node("scene_preview", "PreviewImage", "Scene reference  /  image 1", (550, 1530), (460, 430))
    g.node("overlay_preview", "PreviewImage", "Teal overlay  /  allowed edit area", (550, 2050), (460, 480))
    g.note("Original · blur · neutral", "Original keeps target pose and expression cues, but can also retain the target identity.\nBlur weakens those cues. Neutral removes the head cues.\nCompare results at a fixed seed before changing defaults.", (30, 2260), (480, 260))
    g.link("template", 0, "scene", "template")
    g.link("mask", 1, "scene", "headmask")
    g.link("scene", 1, "scene_preview", "images")
    g.link("scene", 3, "overlay_preview", "images")

    g.note("One clear direction  /  one reproducible sample", "Swap Direction builds the prompt using the actual number and order of reference views. Extra instructions are optional.\nThe default sampler uses CFG 1 and full denoise for the distilled 9B model.", (1150, 1320), (980, 130))
    g.node("prompt", "DP_SwapPrompt", "Swap Direction  /  optional extra instructions", (1150, 1530), (450, 400), {"extra_instructions": ""})
    g.node("conditioning", "DP_KleinConditioning", "Klein Conditioning  /  scene then identity", (1650, 1530), (480, 360))
    g.node("swap", "DP_DreamSwap", "DreamSwap  /  Klein 9B", (1150, 2060), (480, 490),
           {"seed": 19347, "steps": 4, "engine": "native", "sampler": "euler", "scheduler": "simple", "lanpaint_steps": 2})
    g.node("decode", "VAEDecode", "Decode generated head crop", (1650, 2060), (480, 200))
    g.note("A/B comparison", "Keep the seed fixed while changing one setting.\nNative is the initial backend. To compare the installed LanPaint sampler, select engine = lanpaint. Its inner-step setting applies only to that engine.\nMore diffusion steps do not guarantee better identity.", (1650, 2370), (480, 250))
    g.link("identity", 0, "prompt", "identity")
    g.link("scene", 0, "prompt", "scene")
    g.link("clip", 0, "conditioning", "clip")
    g.link("vae", 0, "conditioning", "vae")
    g.link("identity", 0, "conditioning", "identity")
    g.link("scene", 0, "conditioning", "scene")
    g.link("prompt", 0, "conditioning", "prompt")
    g.link("model", 0, "swap", "model")
    g.link("conditioning", 0, "swap", "positive")
    g.link("conditioning", 1, "swap", "negative")
    g.link("conditioning", 2, "swap", "masked_latent")
    g.link("swap", 0, "decode", "samples")
    g.link("vae", 0, "decode", "vae")

    g.note("The original page remains the canvas", "Seam Finish restores the original resolution and copies every protected pixel exactly. Color correction starts at 0.\nReview the identity, hair, pose and realism yourself. REVIEW confirms pixel checks, not face quality.", (2270, 1320), (1220, 130))
    g.node("finish", "DP_SeamFinish", "Seam Finish  /  exact page composite", (2270, 1530), (520, 380),
           {"color_strength": 0.0, "max_shift": 0.04})
    g.node("save", "SaveImage", "FINAL PAGE  /  original dimensions", (2850, 1530), (640, 570),
           {"filename_prefix": "DreamPage/Studio/final"}, "#67543d")
    g.node("review", "DP_ReviewBoard", "Review Board  /  identity + protected pixels", (2270, 2020), (520, 330), {"tile_size": 384})
    g.node("review_save", "SaveImage", "REVIEW BOARD  /  compare before & after", (2270, 2460), (1220, 320),
           {"filename_prefix": "DreamPage/Studio/review"}, "#67543d")
    g.link("decode", 0, "finish", "generated_crop")
    g.link("scene", 0, "finish", "scene")
    g.link("finish", 0, "save", "images")
    g.link("finish", 0, "review", "final_image")
    g.link("scene", 0, "review", "scene")
    g.link("references", 0, "review", "references")
    g.link("review", 0, "review_save", "images")
    return g


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", default="http://127.0.0.1:8188")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "workflows")
    args = parser.parse_args()
    graph = build(get_schemas(args.server))
    graph.validate()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for filename, data in (("DreamPage_Klein9B_Studio.json", graph.workflow()),
                           ("DreamPage_Klein9B_Studio_api.json", graph.api)):
        path = args.output_dir / filename
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(path)
    print(f"Validated {len(graph.nodes)} nodes, {len(graph.links)} links, {len(graph.groups)} groups. No job queued.")


if __name__ == "__main__":
    main()
