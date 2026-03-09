//
//  EnumCasesCommand.swift
//  Sextant
//
//  Created by Mathew Gacy on 3/8/26.
//  Copyright © 2026 Mathew Gacy. All rights reserved.
//

import ArgumentParser
import SextantLib

/// Searches for enum cases, optionally filtering by pattern.
///
/// Accepts a path (file or directory) and an optional `--pattern` regex. Parses all Swift files
/// found at the path and uses `StructuralQuery` to find matching enum cases. Outputs JSON with
/// enum name, case name, associated values, file, and line.
struct EnumCasesCommand: ParsableCommand {
    static let configuration = CommandConfiguration(
        commandName: "enum-cases",
        abstract: "Search for enum cases with optional pattern filtering"
    )

    @Argument(help: "Path to a Swift file or directory to scan")
    var path: String

    @Option(name: .long, help: "Regex pattern to match against full case declaration")
    var pattern: String?

    @Option(name: .long, help: "Filter by enum name (exact match)")
    var enumName: String?

    @OptionGroup var output: OutputOptions

    func run() throws {
        let query = StructuralQuery()
        let overviews = try scanAndParse(at: path, relativeTo: output.absolute ? nil : path)

        var results: [EnumCaseMatch]
        if let pattern {
            results = try query.findEnumCases(matching: pattern, in: overviews)
        } else {
            results = query.allEnumCases(in: overviews)
        }

        if let enumName {
            results = results.filter { $0.enumName == enumName }
        }

        try printJSON(results, pretty: output.pretty)
    }
}
