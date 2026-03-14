//
//  ParseResult.swift
//  Sextant
//
//  Created by Mathew Gacy on 3/13/26.
//  Copyright © 2026 Mathew Gacy. All rights reserved.
//

/// A file that failed to parse.
public struct ParseFailure: Sendable {

    /// The path to the file that could not be parsed.
    public let file: String

    /// The error encountered during parsing.
    public let error: FileParser.Error

    /// Creates a parse failure.
    ///
    /// - Parameters:
    ///   - file: The path to the file that could not be parsed.
    ///   - error: The error encountered during parsing.
    public init(file: String, error: FileParser.Error) {
        self.file = file
        self.error = error
    }
}

/// The result of parsing multiple Swift files concurrently.
///
/// Contains successfully parsed file overviews and any file-level failures.
/// Both collections are sorted by file path for deterministic output.
public struct ParseResult: Sendable {

    /// Successfully parsed file overviews, sorted by file path.
    public let overviews: [FileOverview]

    /// Files that failed to parse, sorted by file path.
    public let failures: [ParseFailure]

    /// The total number of files that were attempted.
    public var totalCount: Int { overviews.count + failures.count }

    /// Whether all attempted files failed to parse.
    public var allFailed: Bool { overviews.isEmpty && !failures.isEmpty }

    /// Creates a parse result.
    ///
    /// - Parameters:
    ///   - overviews: Successfully parsed file overviews.
    ///   - failures: Files that failed to parse with their errors.
    public init(overviews: [FileOverview], failures: [ParseFailure]) {
        self.overviews = overviews
        self.failures = failures
    }
}
