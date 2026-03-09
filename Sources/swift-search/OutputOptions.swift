//
//  OutputOptions.swift
//  Sextant
//
//  Created by Mathew Gacy on 3/8/26.
//  Copyright © 2026 Mathew Gacy. All rights reserved.
//

import ArgumentParser

/// Shared output formatting options for all subcommands.
///
/// Output defaults to compact JSON with relative paths (optimized for agent consumption).
/// Use `--pretty` and `--absolute` for human-readable debugging output.
struct OutputOptions: ParsableArguments {
    @Flag(name: .long, help: "Pretty-print JSON output")
    var pretty = false

    @Flag(name: .long, help: "Output absolute file paths instead of relative")
    var absolute = false
}
