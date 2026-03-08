//
//  SwiftSearch.swift
//  Sextant
//
//  Created by Mathew Gacy on 3/8/26.
//  Copyright © 2026 Mathew Gacy. All rights reserved.
//

import ArgumentParser

/// Structural Swift code search tool.
///
/// Parses Swift source files using SyntaxSparrow and provides structured queries that go beyond
/// what grep or LSP can offer.
@main
struct SwiftSearch: ParsableCommand {
    static let configuration = CommandConfiguration(
        commandName: "swift-search",
        abstract: "Structural Swift code search",
        version: Version.number,
        subcommands: [
            OverviewCommand.self,
            EnumCasesCommand.self,
            LookupCommand.self
        ]
    )
}
