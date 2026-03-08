//
//  LookupCommand.swift
//  Sextant
//
//  Created by Mathew Gacy on 3/8/26.
//  Copyright © 2026 Mathew Gacy. All rights reserved.
//

import ArgumentParser
import Foundation
import SwiftSearchLib

/// Looks up a symbol by name with optional kind filtering.
///
/// Scans the given path (or current directory by default) for Swift files, builds a `SymbolTable`,
/// and looks up the symbol. Outputs JSON results with name, kind, file, line, and attributes.
struct LookupCommand: ParsableCommand {
    static let configuration = CommandConfiguration(
        commandName: "lookup",
        abstract: "Look up a symbol by name"
    )

    @Argument(help: "Symbol name to search for")
    var name: String

    @Option(name: .long, help: "Filter by symbol kind (struct, class, enum, protocol, typealias, function, variable, case)")
    var kind: SymbolKind?

    @Option(name: .long, help: "Path to scan (default: current directory)")
    var path: String = "."

    func run() throws {
        let scanner = FileScanner()
        let parser = FileParser()

        let files = try scanner.collectSwiftFiles(at: path)
        var overviews: [FileOverview] = []
        for file in files {
            do {
                overviews.append(try parser.parseFile(at: file))
            } catch {
                fputs("warning: \(error.localizedDescription)\n", stderr)
            }
        }

        let table = SymbolTable(overviews: overviews)

        let results: [SymbolEntry]
        if let kind {
            results = table.lookup(name: name, kind: kind)
        } else {
            results = table.lookup(name: name)
        }

        try printJSON(results)
    }
}
