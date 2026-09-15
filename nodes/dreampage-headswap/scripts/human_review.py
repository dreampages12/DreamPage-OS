"""Blind A/B human review packets: create, store responses, summarize.

Voter files carry no method names or original paths, and A/B order is randomized per trial.
Counts are raw preferences, not calibrated identity or realism scores.
"""
from __future__ import annotations

import argparse
import json

from dreampage_headswap.evaluation.human import create_blind_packet, store_responses, summarize_responses


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create", help="Build a voter packet and its private assignment key")
    create.add_argument("--manifest", required=True, help="Benchmark manifest with current_result and new_result")
    create.add_argument("--destination", required=True, help="Must not already exist")
    create.add_argument("--seed", type=int, help="Omit for a fresh random assignment")

    store = sub.add_parser("store", help="Append validated responses to a JSONL response log")
    store.add_argument("--packet-dir", required=True, help="The voter directory containing tasks.json")
    store.add_argument("--responses", required=True)
    store.add_argument("--destination", required=True)

    summarize = sub.add_parser("summarize", help="Unblind stored responses using the private key")
    summarize.add_argument("--assignments", required=True)
    summarize.add_argument("--responses", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "create":
        result = create_blind_packet(args.manifest, args.destination, seed=args.seed)
    elif args.command == "store":
        result = {"accepted_responses": store_responses(args.packet_dir, args.responses, args.destination),
                  "response_log": args.destination}
    else:
        result = summarize_responses(args.assignments, args.responses)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
