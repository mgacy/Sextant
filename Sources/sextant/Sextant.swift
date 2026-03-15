//
//  Sextant.swift
//  Sextant
//
//  Created by Mathew Gacy on 3/8/26.
//  Copyright © 2026 Mathew Gacy. All rights reserved.
//

import ArgumentParser

/// Structural Swift code search tool.
///
/// Parses Swift source files using swift-syntax and provides structured queries that go beyond
/// what grep or LSP can offer.
@main
struct Sextant: AsyncParsableCommand {
    static let configuration = CommandConfiguration(
        commandName: "sextant",
        abstract: "Structural Swift code search",
        version: Version.number,
        subcommands: [
            OverviewCommand.self,
            EnumCasesCommand.self,
            LookupCommand.self,
            ReferencesCommand.self
        ]
    )
}
