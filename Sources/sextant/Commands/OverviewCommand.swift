//
//  OverviewCommand.swift
//  Sextant
//
//  Created by Mathew Gacy on 3/8/26.
//  Copyright © 2026 Mathew Gacy. All rights reserved.
//

import ArgumentParser
import SextantLib

/// Displays a structural overview of declarations in Swift files.
///
/// Accepts a file or directory path. Parses all Swift files found at the path and outputs a JSON
/// array of file overviews including file path, declarations with name, kind, line, attributes,
/// children, and conformances.
struct OverviewCommand: ParsableCommand {
    static let configuration = CommandConfiguration(
        commandName: "overview",
        abstract: "Show structural overview of Swift files"
    )

    @Argument(help: "Path to a Swift file or directory to scan")
    var path: String

    @OptionGroup var output: OutputOptions

    func run() throws {
        let overviews = try scanAndParse(at: path, relativeTo: output.absolute ? nil : path)
        try printJSON(overviews, pretty: output.pretty)
    }
}
