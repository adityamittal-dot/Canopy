"""Dump a single file's extracted symbols as JSON, for manual inspection."""
import argparse
import dataclasses
import json

from parsing.extract import extract_symbols
from parsing.parse import parse_file

parser = argparse.ArgumentParser()
parser.add_argument('path')
parser.add_argument('--module-name', default='mod')
args = parser.parse_args()

symbols = extract_symbols(parse_file(args.path), args.path, args.module_name)
print(json.dumps([dataclasses.asdict(s) for s in symbols], indent=2))
