//
//  ScanAndParse.swift
//  Sextant
//
//  Created by Mathew Gacy on 3/8/26.
//  Copyright © 2026 Mathew Gacy. All rights reserved.
//

import ArgumentParser
import Foundation
import SwiftSearchLib

/// Scans and parses all Swift files at the given path.
///
/// Logs warnings to stderr for files that fail to parse. Throws `ValidationError`
/// if all files fail.
///
/// - Parameter path: A file or directory path to scan.
/// - Returns: An array of parsed file overviews.
func scanAndParse(at path: String) throws -> [FileOverview] {
    let scanner = FileScanner()
    let parser = FileParser()
    let files = try scanner.collectSwiftFiles(at: path)
    var overviews: [FileOverview] = []
    var failureCount = 0
    for file in files {
        do {
            overviews.append(try parser.parseFile(at: file))
        } catch {
            fputs("warning: \(error.localizedDescription)\n", stderr)
            failureCount += 1
        }
    }

    if failureCount > 0 {
        fputs("warning: \(failureCount) of \(files.count) files could not be parsed\n", stderr)
    }

    if !files.isEmpty && overviews.isEmpty {
        throw ValidationError(
            "All \(files.count) files failed to parse. Check file permissions and encoding."
        )
    }

    return overviews
}
