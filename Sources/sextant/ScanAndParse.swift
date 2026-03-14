//
//  ScanAndParse.swift
//  Sextant
//
//  Created by Mathew Gacy on 3/8/26.
//  Copyright © 2026 Mathew Gacy. All rights reserved.
//

import ArgumentParser
import Foundation
import SextantLib

/// Scans and parses all Swift files at the given path concurrently.
///
/// Files are parsed in parallel using a `TaskGroup`. Results are sorted by file path
/// for deterministic output. Logs warnings to stderr for files that fail to parse.
/// Throws `ValidationError` if all files fail.
///
/// - Parameters:
///   - path: A file or directory path to scan.
///   - relativeTo: When provided, file paths in the returned overviews are made relative to this
///     path. If the path is a directory it is used directly; if a file, its parent directory is used.
/// - Returns: An array of parsed file overviews.
func scanAndParse(at path: String, relativeTo basePath: String? = nil) async throws -> [FileOverview] {
    let scanner = FileScanner()
    let parser = FileParser()
    let files = try scanner.collectSwiftFiles(at: path)

    let results = await withTaskGroup(of: (String, Result<FileOverview, any Error>).self) { group in
        for file in files {
            group.addTask {
                do {
                    return (file, .success(try parser.parseFile(at: file)))
                } catch {
                    return (file, .failure(error))
                }
            }
        }

        var collected: [(String, Result<FileOverview, any Error>)] = []
        collected.reserveCapacity(files.count)
        for await result in group {
            collected.append(result)
        }
        return collected
    }

    // Sort by file path for deterministic output (matches FileScanner's sort order).
    let sorted = results.sorted { $0.0 < $1.0 }

    var overviews: [FileOverview] = []
    overviews.reserveCapacity(files.count)
    var failureCount = 0

    for (_, result) in sorted {
        switch result {
        case .success(let overview):
            overviews.append(overview)
        case .failure(let error):
            fputs("warning: \(error.localizedDescription)\n", stderr)
            failureCount += 1
        }
    }

    if failureCount > 0 {
        fputs("warning: \(failureCount) of \(files.count) files could not be parsed\n", stderr)
    }

    if !files.isEmpty && overviews.isEmpty {
        throw ValidationError("All \(files.count) files failed to parse. Check file permissions and encoding.")
    }

    if let basePath {
        let prefix = resolveBasePrefix(basePath)
        return overviews.map { overview in
            let relativePath = overview.file.hasPrefix(prefix)
                ? String(overview.file.dropFirst(prefix.count))
                : overview.file
            return FileOverview(file: relativePath, declarations: overview.declarations)
        }
    }

    return overviews
}

/// Resolves a path to an absolute directory prefix ending with "/".
///
/// - Parameter path: A file or directory path.
/// - Returns: The resolved directory path with a trailing slash.
private func resolveBasePrefix(_ path: String) -> String {
    let url = URL(fileURLWithPath: path).standardized
    var isDir: ObjCBool = false
    FileManager.default.fileExists(atPath: url.path, isDirectory: &isDir)
    let dir = isDir.boolValue ? url.path : url.deletingLastPathComponent().path
    return dir.hasSuffix("/") ? dir : dir + "/"
}
