# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

TT Memory Profiler - Memory profiler for Tenstorrent hardware that extracts per-operation memory statistics from TT-XLA runtime logs and generates interactive HTML visualizations.

## Installation & Development

```bash
# Install locally for development
pip install -e /path/to/tt-memory-profiler
```

## Commands

```bash
# Interactive CLI (recommended for remote development)
ttmem

# Full profiling pipeline (run + parse + visualize)
tt-memory-profiler path/to/your_model.py

# Capture logs only
tt-memory-profiler --log path/to/your_model.py

# Parse existing log file
tt-memory-profiler --analyze logs/script_*/script_profile.log

# Generate visualization from parsed data
tt-memory-profiler --visualize logs/script_YYYYMMDD_HHMMSS/

# Extract last run from multi-pass logs (removes warmup)
python memory_profiler/extract_last_run.py logs/*/script_profile.log

# Standalone visualization generation
python memory_profiler/generate_viz.py logs/script_YYYYMMDD_HHMMSS/
```

## Architecture

### Processing Pipeline

1. **interactive_cli.py** - Interactive CLI (`ttmem`), guides users through log processing with built-in HTTP server for remote access
2. **run_profiled.py** - CLI entry point (`tt-memory-profiler`), orchestrates the pipeline with 4 modes: default (full), --log, --analyze, --visualize
3. **parser.py** - Main log parser, coordinates all sub-parsers and produces synchronized JSON outputs
4. **mlir_parser.py** - Extracts MLIR operation details (op names, shapes, dtypes, attributes) using regex
5. **memory_parser.py** - Parses memory state blocks (DRAM, L1, L1_SMALL, TRACE) from log lines
6. **inputs_registry_parser.py** - Extracts function argument registry (parameters/constants/inputs) from MLIR module dumps
7. **visualizer.py** - Generates interactive HTML reports with Plotly.js

### Key Design Patterns

- **Synchronized JSON outputs**: The nth element in `memory.json` corresponds to the nth element in `operations.json`
- **Import compatibility**: Modules use try/except for relative vs absolute imports to work both as package and standalone scripts
- **const_eval tracking**: Operations are classified as weight vs activation based on const_eval graph detection

### Output Structure

```
./logs/<script_name>_YYYYMMDD_HHMMSS/
├── <script_name>_profile.log         # Raw runtime logs
├── <script_name>_memory.json         # Memory stats per operation
├── <script_name>_operations.json     # Operation metadata
├── <script_name>_inputs_registry.json # Weights/constants/inputs registry
└── <script_name>_report.html         # Interactive visualization
```

## Prerequisites

Requires TT-XLA configured for memory logging:
1. Enable `tt::runtime::setMemoryLogLevel(tt::runtime::MemoryLogLevel::Operation)` in TT-XLA
2. Build TT-XLA with `-DCMAKE_BUILD_TYPE=Debug -DTT_RUNTIME_DEBUG=ON`
3. Export `TTMLIR_RUNTIME_LOGGER_LEVEL=DEBUG`
