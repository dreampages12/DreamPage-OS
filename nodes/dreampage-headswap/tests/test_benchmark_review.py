"""Benchmark and blind-review infrastructure.

The point of these tests is that the comparison cannot quietly become dishonest: inputs must be
byte-identical, stored results must match their run records, benchmark identities must not
appear in training, unmeasured metrics must stay null, and voters must not be able to tell which
image came from which system.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from _fixtures import load_script, rights, write_image, write_mask
from dreampage_headswap.data.records import file_sha256, read_jsonl, write_jsonl
from dreampage_headswap.evaluation.benchmark import archive_baseline, benchmark, record_stored_result
from dreampage_headswap.evaluation.human import create_blind_packet, store_responses, summarize_responses

TAGS = ["frontal_to_frontal", "neutral", "generated_template"]


def _result(template: np.ndarray, mask: np.ndarray, path: Path, fill) -> Path:
    """A stored 'result': the template with the editable region painted a flat colour."""
    image = template.copy()
    image[mask > 0] = fill
    Image.fromarray(image).save(path)
    return path


class BenchmarkFixture:
    """One complete two-method benchmark case on disk, including run provenance records."""

    def __init__(self, root: Path, *, identity_id: str = "bench_identity", case_id: str = "case_001"):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.source = write_image(root / "source.png", 41, (48, 48))
        self.template_path = write_image(root / "template.png", 42, (64, 48))
        self.mask_path = write_mask(root / "mask.png", (64, 48), (18, 10, 46, 38))
        with Image.open(self.template_path) as image:
            self.template = np.asarray(image.convert("RGB")).copy()
        with Image.open(self.mask_path) as image:
            self.mask = np.asarray(image.convert("L")).astype(np.float32) / 255
        self.current = _result(self.template, self.mask, root / "current.png", (200, 40, 40))
        self.new = _result(self.template, self.mask, root / "new.png", (40, 200, 40))
        self.workflow = root / "workflow.json"
        self.workflow.write_text(json.dumps({"nodes": []}), encoding="utf-8")
        self.config = root / "config.yaml"
        self.config.write_text("steps: 28\n", encoding="utf-8")
        self.runs = {}
        for method, result in (("current_klein_v6", self.current), ("dreamswap_r0", self.new)):
            destination = root / f"{method}.run.json"
            record_stored_result(source=self.source, template=self.template_path, headmask=self.mask_path,
                                 result=result, workflow=self.workflow, config=self.config,
                                 method_id=method, destination=destination,
                                 performance={"latency_ms": 8200.0, "peak_vram_bytes": 12_000_000_000,
                                              "measurement_protocol": "warm run, 1 warmup, excludes model load",
                                              "hardware": "RTX 3090 24GB", "device": "cuda:0", "warmup_runs": 1})
            self.runs[method] = destination
        self.case = {"case_id": case_id, "identity_id": identity_id, "split": "test", "tags": TAGS,
                     "synthetic": True, "source": str(self.source), "template": str(self.template_path),
                     "headmask": str(self.mask_path), "current_result": str(self.current),
                     "new_result": str(self.new), "current_run": str(self.runs["current_klein_v6"]),
                     "new_run": str(self.runs["dreamswap_r0"])}

    def manifest(self, name: str = "benchmark.jsonl", cases=None) -> Path:
        path = self.root / name
        write_jsonl(path, cases or [self.case])
        return path


class ArchiveTests(unittest.TestCase):
    def test_baseline_archive_records_checksums_and_does_not_execute(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workflow = root / "workflow_api.json"
            workflow.write_text(json.dumps({"192": {}}), encoding="utf-8")
            config = root / "config.json"
            config.write_text(json.dumps({"book": "test"}), encoding="utf-8")
            metadata = archive_baseline(workflow, config, root / "archive")
            self.assertFalse(metadata["executed"])
            self.assertEqual(metadata["workflow_sha256"], file_sha256(workflow))
            self.assertTrue((root / "archive" / "workflow.json").is_file())
            with self.assertRaises(FileExistsError):
                archive_baseline(workflow, config, root / "archive")


class RunRecordTests(unittest.TestCase):
    def test_performance_numbers_require_a_protocol_and_hardware(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = BenchmarkFixture(Path(tmp))
            with self.assertRaisesRegex(ValueError, "measurement protocol and hardware"):
                record_stored_result(source=fixture.source, template=fixture.template_path,
                                     headmask=fixture.mask_path, result=fixture.current,
                                     workflow=fixture.workflow, config=fixture.config,
                                     method_id="x", destination=Path(tmp) / "bad.json",
                                     performance={"latency_ms": 100.0})

    def test_a_method_id_is_mandatory(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = BenchmarkFixture(Path(tmp))
            with self.assertRaisesRegex(ValueError, "method_id"):
                record_stored_result(source=fixture.source, template=fixture.template_path,
                                     headmask=fixture.mask_path, result=fixture.current,
                                     workflow=fixture.workflow, config=fixture.config,
                                     method_id="", destination=Path(tmp) / "bad.json")


class CompareTests(unittest.TestCase):
    def test_synthetic_cases_need_an_explicit_opt_in(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = BenchmarkFixture(Path(tmp))
            with self.assertRaisesRegex(ValueError, "not a quality benchmark"):
                benchmark(fixture.manifest(), Path(tmp) / "out")

    def test_report_measures_preservation_and_leaves_unmeasured_metrics_null(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = BenchmarkFixture(Path(tmp))
            report = benchmark(fixture.manifest(), Path(tmp) / "out", allow_synthetic=True)
            self.assertEqual(report["case_count"], 1)
            self.assertIn("NOT A QUALITY BENCHMARK", report["purpose"])
            case = report["cases"][0]
            for method in ("current", "new"):
                metrics = case[method]["metrics"]
                self.assertTrue(metrics["outside_mask_exact"])
                self.assertIsNone(metrics["identity_similarity"])
                self.assertIsNone(metrics["realism"])
                self.assertIsNone(metrics["pose_preservation"])
            self.assertEqual(case["performance_delta_new_minus_current"]["latency_ms"], 0.0)
            self.assertFalse(report["split_audit"]["complete"])
            self.assertIn("hair_crossing_boundary", report["missing_recommended_tags"])
            self.assertTrue(Path(case["grid"]).is_file())
            self.assertTrue((Path(tmp) / "out" / "report.json").is_file())

    def test_a_result_edited_after_its_run_record_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = BenchmarkFixture(Path(tmp))
            manifest = fixture.manifest()
            tampered = np.asarray(Image.open(fixture.new).convert("RGB")).copy()
            tampered[0, 0] = (1, 2, 3)
            Image.fromarray(tampered).save(fixture.new)
            with self.assertRaisesRegex(ValueError, "changed since run record"):
                benchmark(manifest, Path(tmp) / "out", allow_synthetic=True)

    def test_the_two_methods_must_have_seen_the_same_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = BenchmarkFixture(Path(tmp))
            other_source = write_image(Path(tmp) / "other_source.png", 99, (48, 48))
            record_stored_result(source=other_source, template=fixture.template_path,
                                 headmask=fixture.mask_path, result=fixture.new,
                                 workflow=fixture.workflow, config=fixture.config,
                                 method_id="dreamswap_r0", destination=fixture.runs["dreamswap_r0"])
            with self.assertRaisesRegex(ValueError, "Input provenance mismatch"):
                benchmark(fixture.manifest(), Path(tmp) / "out", allow_synthetic=True)

    def test_a_benchmark_identity_that_appears_in_training_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = BenchmarkFixture(root)
            training = root / "pairs.train.jsonl"
            source = write_image(root / "train_source.png", 61, (48, 48))
            template = write_image(root / "train_template.png", 62, (48, 48))
            mask = write_mask(root / "train_mask.png", (48, 48), (8, 8, 30, 30))
            write_jsonl(training, [{"pair_id": "p1", "identity_id": "bench_identity", "split": "train",
                                    "rights": rights(), "synthetic": True, "source": str(source),
                                    "sources": [str(source)], "template": str(template),
                                    "headmask": str(mask), "ground_truth": str(template)}])
            with self.assertRaisesRegex(ValueError, "leaks into training"):
                benchmark(fixture.manifest(), root / "out", training_manifests=[training], allow_synthetic=True)

    def test_benchmark_image_content_reused_in_training_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = BenchmarkFixture(root)
            training = root / "pairs.train.jsonl"
            other = write_image(root / "train_source.png", 71, (64, 48))
            mask = write_mask(root / "train_mask.png", (64, 48), (8, 8, 30, 30))
            write_jsonl(training, [{"pair_id": "p1", "identity_id": "someone_else", "split": "train",
                                    "rights": rights(), "synthetic": True, "source": str(other),
                                    "sources": [str(other)], "template": str(fixture.template_path),
                                    "headmask": str(mask), "ground_truth": str(fixture.template_path)}])
            with self.assertRaisesRegex(ValueError, "overlaps training"):
                benchmark(fixture.manifest(), root / "out", training_manifests=[training], allow_synthetic=True)

    def test_cases_need_coverage_tags_and_a_test_split(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = BenchmarkFixture(Path(tmp))
            untagged = {**fixture.case, "tags": []}
            with self.assertRaisesRegex(ValueError, "coverage tags"):
                benchmark(fixture.manifest("untagged.jsonl", [untagged]), Path(tmp) / "a", allow_synthetic=True)
            trained_on = {**fixture.case, "split": "train"}
            with self.assertRaisesRegex(ValueError, "test/benchmark split"):
                benchmark(fixture.manifest("split.jsonl", [trained_on]), Path(tmp) / "b", allow_synthetic=True)

    def test_benchmark_script_reports_coverage_and_gaps(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = BenchmarkFixture(Path(tmp))
            script = load_script("benchmark")
            import contextlib
            import io
            stream = io.StringIO()
            with contextlib.redirect_stdout(stream):
                code = script.main(["compare", "--manifest", str(fixture.manifest()),
                                    "--output-dir", str(Path(tmp) / "out"), "--allow-synthetic"])
            self.assertEqual(code, 0)
            printed = json.loads(stream.getvalue())
            self.assertEqual(printed["case_count"], 1)
            self.assertFalse(printed["split_audit_complete"])
            self.assertEqual(printed["coverage"]["frontal_to_frontal"], 1)


class HumanReviewTests(unittest.TestCase):
    def test_voter_packet_hides_the_method_and_summary_unblinds_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = BenchmarkFixture(root)
            packet = create_blind_packet(fixture.manifest(), root / "review", seed=1234)
            voter = Path(packet["voter_directory"])
            tasks = json.loads((voter / "tasks.json").read_text(encoding="utf-8"))
            self.assertEqual(packet["trial_count"], 1)
            self.assertIn("Synthetic", tasks["fixture_notice"])
            blob = (voter / "tasks.json").read_text(encoding="utf-8") + (voter / "index.html").read_text(encoding="utf-8")
            for secret in ("current", "dreamswap", "klein", str(fixture.new.name)):
                self.assertNotIn(secret, blob.lower().replace("current_system", ""))
            self.assertTrue((voter / "response.schema.json").is_file())

            trial = tasks["trials"][0]["trial_id"]
            responses = root / "responses.json"
            responses.write_text(json.dumps([{"trial_id": trial, "voter_id": "voter_a", "answers":
                                              {key: "A" for key in tasks["questions"]}}]), encoding="utf-8")
            log = root / "responses.jsonl"
            self.assertEqual(store_responses(voter, responses, log), 1)
            with self.assertRaisesRegex(ValueError, "Duplicate response"):
                store_responses(voter, responses, log)

            assignments = Path(packet["private_directory"]) / "assignments.json"
            summary = summarize_responses(assignments, log)
            self.assertEqual(summary["response_count"], 1)
            chosen = json.loads(assignments.read_text(encoding="utf-8"))["assignments"][0]["A"]
            self.assertEqual(summary["counts"]["realism"][chosen], 1)
            self.assertIn("not calibrated", summary["interpretation"])

    def test_malformed_responses_are_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = BenchmarkFixture(root)
            packet = create_blind_packet(fixture.manifest(), root / "review", seed=7)
            voter = Path(packet["voter_directory"])
            tasks = json.loads((voter / "tasks.json").read_text(encoding="utf-8"))
            trial = tasks["trials"][0]["trial_id"]
            complete = {key: "A" for key in tasks["questions"]}
            bad = [[{"trial_id": "unknown", "voter_id": "v", "answers": complete}],
                   [{"trial_id": trial, "voter_id": "", "answers": complete}],
                   [{"trial_id": trial, "voter_id": "v", "answers": {**complete, "realism": "maybe"}}],
                   [{"trial_id": trial, "voter_id": "v", "answers": {"realism": "A"}}]]
            for index, rows in enumerate(bad):
                path = root / f"bad_{index}.json"
                path.write_text(json.dumps(rows), encoding="utf-8")
                with self.assertRaises(ValueError):
                    store_responses(voter, path, root / f"log_{index}.jsonl")

    def test_a_fresh_directory_is_required_so_packets_cannot_mix(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = BenchmarkFixture(root)
            create_blind_packet(fixture.manifest(), root / "review", seed=1)
            with self.assertRaises(FileExistsError):
                create_blind_packet(fixture.manifest(), root / "review", seed=1)

    def test_review_script_creates_stores_and_summarizes(self):
        with tempfile.TemporaryDirectory() as tmp:
            import contextlib
            import io
            root = Path(tmp)
            fixture = BenchmarkFixture(root)
            script = load_script("human_review")
            stream = io.StringIO()
            with contextlib.redirect_stdout(stream):
                script.main(["create", "--manifest", str(fixture.manifest()),
                             "--destination", str(root / "review"), "--seed", "5"])
            created = json.loads(stream.getvalue())
            voter = Path(created["voter_directory"])
            tasks = json.loads((voter / "tasks.json").read_text(encoding="utf-8"))
            responses = root / "responses.json"
            responses.write_text(json.dumps([{"trial_id": tasks["trials"][0]["trial_id"],
                                              "voter_id": "voter_b",
                                              "answers": {key: "cannot_judge" for key in tasks["questions"]}}]),
                                 encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                script.main(["store", "--packet-dir", str(voter), "--responses", str(responses),
                             "--destination", str(root / "log.jsonl")])
            stream = io.StringIO()
            with contextlib.redirect_stdout(stream):
                script.main(["summarize", "--assignments",
                             str(Path(created["private_directory"]) / "assignments.json"),
                             "--responses", str(root / "log.jsonl")])
            summary = json.loads(stream.getvalue())
            self.assertEqual(summary["counts"]["identity"]["cannot_judge"], 1)
            self.assertEqual(len(read_jsonl(root / "log.jsonl")), 1)


class EvaluateScriptTests(unittest.TestCase):
    def test_quality_script_measures_preservation_and_cannot_pass_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            import contextlib
            import io
            root = Path(tmp)
            fixture = BenchmarkFixture(root)
            script = load_script("evaluate")
            stream = io.StringIO()
            with contextlib.redirect_stdout(stream):
                code = script.main(["--template", str(fixture.template_path), "--output", str(fixture.new),
                                    "--mask", str(fixture.mask_path), "--report", str(root / "quality.json")])
            self.assertEqual(code, 0)
            report = json.loads(stream.getvalue())
            self.assertEqual(report["quality"]["status"], "RETRY")
            self.assertEqual(report["quality"]["template_preservation_score"], 1.0)
            self.assertIsNone(report["quality"]["identity_score"])
            self.assertTrue((root / "quality.json").is_file())

    def test_a_drifted_result_fails_the_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            import contextlib
            import io
            root = Path(tmp)
            fixture = BenchmarkFixture(root)
            drifted = np.asarray(Image.open(fixture.new).convert("RGB")).copy()
            drifted[0, 0] = (0, 0, 0)
            path = root / "drifted.png"
            Image.fromarray(drifted).save(path)
            script = load_script("evaluate")
            with contextlib.redirect_stdout(io.StringIO()):
                code = script.main(["--template", str(fixture.template_path), "--output", str(path),
                                    "--mask", str(fixture.mask_path)])
            self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
