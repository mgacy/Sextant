//
//  LookupCommand.swift
//  Sextant
//
//  Created by Mathew Gacy on 3/8/26.
//  Copyright © 2026 Mathew Gacy. All rights reserved.
//

import ArgumentParser
import SextantLib

/// Looks up a symbol by name with optional kind filtering.
///
/// Scans the given path (or current directory by default) for Swift files, builds a `SymbolTable`,
/// and looks up the symbol. Outputs JSON results with name, kind, file, line, and attributes.
struct LookupCommand: AsyncParsableCommand {
    static let configuration = CommandConfiguration(
        commandName: "lookup",
        abstract: "Look up a symbol by name"
    )

    @Argument(help: "Symbol name to search for")
    var name: String

    @Option(name: .long, help: "Filter by symbol kind (struct, class, enum, protocol, typealias, function, variable, case, initializer, extension, actor, macro)")
    var kind: SymbolKind?

    @Option(name: .long, help: "Path to scan (default: current directory)")
    var path: String = "."

    @OptionGroup var output: OutputOptions

    func run() async throws {
        let overviews = try await scanAndParse(at: path, relativeTo: output.absolute ? nil : path)
        let table = SymbolTable(overviews: overviews)

        let results: [SymbolEntry]
        if let kind {
            results = table.lookup(name: name, kind: kind)
        } else {
            results = table.lookup(name: name)
        }

        try printJSON(results, pretty: output.pretty)
    }
}
