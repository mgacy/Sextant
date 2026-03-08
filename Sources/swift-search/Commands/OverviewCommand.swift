//
//  OverviewCommand.swift
//  Sextant
//
//  Created by Mathew Gacy on 3/8/26.
//  Copyright © 2026 Mathew Gacy. All rights reserved.
//

import ArgumentParser
import SwiftSearchLib

/// Displays a structural overview of declarations in a Swift file.
///
/// Parses the file with `FileParser` and outputs a JSON array of declarations including name, kind,
/// line, attributes, children, and conformances.
struct OverviewCommand: ParsableCommand {
    static let configuration = CommandConfiguration(
        commandName: "overview",
        abstract: "Show structural overview of a Swift file"
    )

    @Argument(help: "Path to a Swift source file")
    var file: String

    func run() throws {
        let parser = FileParser()
        let overview = try parser.parseFile(at: file)
        try printJSON(overview.declarations)
    }
}
