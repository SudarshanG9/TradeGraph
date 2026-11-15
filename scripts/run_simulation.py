#!/usr/bin/env python3
"""Run an isolated deterministic native-store demo; no bootstrap or database reset."""
from pathlib import Path
import argparse
import json
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.simulator.market_simulator import run


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seed',type=int,default=20261115)
    parser.add_argument('--report',type=Path,help='Optional JSON evidence output; credentials are never included')
    args=parser.parse_args()
    report=run(args.seed)
    text=json.dumps(report,default=str,indent=2)
    if args.report: args.report.write_text(text+'\n')
    print(text)


if __name__=='__main__': main()
