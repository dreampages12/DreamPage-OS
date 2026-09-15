"""Randomized blind A/B packets. Public files contain no method names or source paths."""
from __future__ import annotations

import hashlib
import json
import random
import secrets
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

from ..data.records import file_sha256, read_jsonl, resolve_asset, write_jsonl
from .benchmark import save_json

QUESTIONS = {
    "identity": "Which looks more like the reference person?",
    "realism": "Which looks more realistic?",
    "template_preservation": "Which preserves the original template better?",
    "less_ai_generated": "Which looks less AI-generated?",
    "integration": "Which has better head/body integration?",
}
CHOICES = ["A", "B", "tie", "cannot_judge"]
RESPONSE_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object",
    "additionalProperties": False, "required": ["trial_id", "voter_id", "answers"],
    "properties": {"trial_id": {"type": "string", "minLength": 1},
                   "voter_id": {"type": "string", "minLength": 1},
                   "answers": {"type": "object", "additionalProperties": False,
                               "required": list(QUESTIONS),
                               "properties": {key: {"enum": CHOICES} for key in QUESTIONS}}},
}


def create_blind_packet(manifest: str | Path, destination: str | Path, *, seed: int | None = None) -> dict:
    manifest, destination = Path(manifest).resolve(), Path(destination).resolve()
    if destination.exists():
        raise FileExistsError("Use a fresh output directory to prevent mixing voter packets")
    seed = secrets.randbits(64) if seed is None else seed
    rng = random.Random(seed)
    raw_cases = read_jsonl(manifest)
    if not raw_cases or len({case.get("case_id") for case in raw_cases}) != len(raw_cases):
        raise ValueError("Expected nonempty manifest with unique case IDs")
    rng.shuffle(raw_cases)
    public, private = destination / "voter", destination / "organizer_private"
    public.mkdir(parents=True)
    private.mkdir()
    trials, assignments = [], []
    for index, case in enumerate(raw_cases):
        trial_id = hashlib.sha256(f"{seed}:{index}:{case['case_id']}".encode()).hexdigest()[:16]
        methods = ["current", "new"]
        rng.shuffle(methods)
        images = {"reference": case["source"], "template": case["template"],
                  "A": case[methods[0] + "_result"], "B": case[methods[1] + "_result"]}
        image_paths, hashes = {}, {}
        for label, path in images.items():
            source = resolve_asset(manifest.parent, path)
            name = f"{trial_id}_{label}.png"
            # Re-encode to strip EXIF, filenames and software metadata that could reveal the method.
            with Image.open(source) as image:
                clean = Image.new("RGB", image.size)
                clean.paste(image.convert("RGB"))
                clean.save(public / name)
            image_paths[label] = name
            hashes[label] = file_sha256(source)
        trials.append({"trial_id": trial_id, "images": image_paths})
        assignments.append({"trial_id": trial_id, "case_id": case["case_id"], "A": methods[0],
                            "B": methods[1], "original_sha256": hashes, "synthetic": case.get("synthetic", False)})
    packet = {"schema_version": 1, "instructions": "Compare A and B using the reference and original template. Choose cannot_judge when uncertain.",
              "questions": QUESTIONS, "choices": CHOICES, "trials": trials,
              "fixture_notice": "Synthetic integration exercise only" if any(case.get("synthetic") for case in raw_cases) else None}
    save_json(public / "tasks.json", packet)
    save_json(public / "response.schema.json", RESPONSE_SCHEMA)
    save_json(private / "assignments.json", {"seed": seed, "manifest_sha256": file_sha256(manifest), "assignments": assignments})
    # Embedded JSON allows this small UI to work from file:// without a web server or fetching private data.
    embedded = json.dumps(packet).replace("<", "\\u003c")
    html = _HTML.replace("__PACKET__", embedded)
    (public / "index.html").write_text(html, encoding="utf-8")
    return {"voter_directory": str(public), "private_directory": str(private), "trial_count": len(trials)}


def store_responses(packet_dir: str | Path, response_file: str | Path, destination: str | Path) -> int:
    packet = json.loads((Path(packet_dir) / "tasks.json").read_text(encoding="utf-8"))
    trials = {trial["trial_id"] for trial in packet["trials"]}
    response_file, destination = Path(response_file), Path(destination)
    if response_file.suffix.lower() == ".jsonl":
        responses = read_jsonl(response_file)
    else:
        responses = json.loads(response_file.read_text(encoding="utf-8"))
        responses = responses if isinstance(responses, list) else [responses]
    existing = read_jsonl(destination) if destination.exists() else []
    seen = {(row["trial_id"], row["voter_id"]) for row in existing}
    accepted = []
    for row in responses:
        if not isinstance(row, dict) or set(row) != {"trial_id", "voter_id", "answers"}:
            raise ValueError("Responses must follow response.schema.json exactly")
        if row["trial_id"] not in trials or not isinstance(row["voter_id"], str) or not row["voter_id"].strip():
            raise ValueError("Unknown trial or missing pseudonymous voter_id")
        if not isinstance(row["answers"], dict) or set(row["answers"]) != set(QUESTIONS):
            raise ValueError("Answer every question; use cannot_judge when needed")
        if any(answer not in CHOICES for answer in row["answers"].values()):
            raise ValueError("Answers must be A, B, tie, or cannot_judge")
        key = row["trial_id"], row["voter_id"]
        if key in seen:
            raise ValueError("Duplicate response for this voter and trial")
        seen.add(key)
        accepted.append({**row, "stored_utc": datetime.now(timezone.utc).isoformat(),
                         "packet_sha256": file_sha256(Path(packet_dir) / "tasks.json")})
    write_jsonl(destination, [*existing, *accepted])
    return len(accepted)


def summarize_responses(assignments_file: str | Path, responses_file: str | Path) -> dict:
    assignment_data = json.loads(Path(assignments_file).read_text(encoding="utf-8"))
    mapping = {row["trial_id"]: row for row in assignment_data["assignments"]}
    summary = {question: {"current": 0, "new": 0, "tie": 0, "cannot_judge": 0} for question in QUESTIONS}
    seen = set()
    for row in read_jsonl(responses_file):
        key = row["trial_id"], row["voter_id"]
        if key in seen or row["trial_id"] not in mapping:
            raise ValueError("Duplicate or unknown trial in stored responses")
        seen.add(key)
        assignment = mapping[row["trial_id"]]
        for question, answer in row["answers"].items():
            summary[question][assignment[answer] if answer in {"A", "B"} else answer] += 1
    return {"counts": summary, "response_count": len(seen),
            "interpretation": "Raw blind preference counts, not calibrated identity or realism scores"}


_HTML = '''<!doctype html><meta charset="utf-8"><title>Blind image comparison</title>
<style>body{font:16px system-ui;margin:24px;background:#f3f4f6;color:#18212b}h1{font-size:24px}.images{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}figure{margin:0}img{width:100%;height:300px;object-fit:contain;background:white}fieldset{margin:12px 0}label{margin-right:18px}button,input{font:inherit;padding:8px}#notice{color:#8b4613}</style>
<h1>Blind image comparison</h1><p id="instructions"></p><p id="notice"></p>
<label>Pseudonymous voter ID <input id="voter" autocomplete="off"></label><main id="trials"></main>
<button id="download">Download responses</button><p id="status"></p>
<script>const packet=__PACKET__;document.querySelector('#instructions').textContent=packet.instructions;
document.querySelector('#notice').textContent=packet.fixture_notice||'';
const root=document.querySelector('#trials');for(const [i,t] of packet.trials.entries()){
const section=document.createElement('section');const title=document.createElement('h2');title.textContent='Comparison '+(i+1);section.append(title);
const images=document.createElement('div');images.className='images';for(const label of ['reference','template','A','B']){const f=document.createElement('figure');const c=document.createElement('figcaption');c.textContent=label;const im=document.createElement('img');im.src=t.images[label];im.alt=label;f.append(c,im);images.append(f)}section.append(images);
for(const [key,q] of Object.entries(packet.questions)){const field=document.createElement('fieldset');const legend=document.createElement('legend');legend.textContent=q;field.append(legend);for(const choice of packet.choices){const l=document.createElement('label');const r=document.createElement('input');r.type='radio';r.name=t.trial_id+'_'+key;r.value=choice;l.append(r,document.createTextNode(choice));field.append(l)}section.append(field)}root.append(section)}
document.querySelector('#download').onclick=()=>{const voter=document.querySelector('#voter').value.trim();const rows=[];if(!voter){document.querySelector('#status').textContent='Enter a pseudonymous voter ID.';return}for(const t of packet.trials){const answers={};for(const key of Object.keys(packet.questions)){const selected=document.querySelector('input[name="'+t.trial_id+'_'+key+'"]:checked');if(!selected){document.querySelector('#status').textContent='Answer every question; choose cannot_judge when uncertain.';return}answers[key]=selected.value}rows.push({trial_id:t.trial_id,voter_id:voter,answers})}const url=URL.createObjectURL(new Blob([JSON.stringify(rows,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='responses.json';a.click();URL.revokeObjectURL(url);document.querySelector('#status').textContent='Response file downloaded.'};</script>'''
