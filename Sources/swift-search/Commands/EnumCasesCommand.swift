//
//  EnumCasesCommand.swift
//  Sextant
//
//  Created by Mathew Gacy on 3/8/26.
//  Copyright © 2026 Mathew Gacy. All rights reserved.
//

import ArgumentParser
import Foundation
import SwiftSearchLib

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

    func run() throws {
        let scanner = FileScanner()
        let parser = FileParser()
        let query = StructuralQuery()

        let files = try scanner.collectSwiftFiles(at: path)
        var overviews: [FileOverview] = []
        for file in files {
            do {
                overviews.append(try parser.parseFile(at: file))
            } catch {
                fputs("warning: \(error.localizedDescription)\n", stderr)
            }
        }

        let results: [EnumCaseMatch]
        if let pattern {
            results = try query.findEnumCases(matching: pattern, in: overviews)
        } else {
            results = query.allEnumCases(in: overviews)
        }

        try printJSON(results)
    }
}
