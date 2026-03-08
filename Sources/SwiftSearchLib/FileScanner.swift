//
//  FileScanner.swift
//  Sextant
//
//  Created by Mathew Gacy on 3/8/26.
//  Copyright © 2026 Mathew Gacy. All rights reserved.
//

import Foundation

/// Walks a directory tree collecting Swift source files.
///
/// Excludes build artifact directories (`.build/`, `checkouts/`, `.index-build/`).
public struct FileScanner: Sendable {

    public enum Error: Swift.Error, LocalizedError, Sendable {
        case pathNotFound(String)
        case directoryUnreadable(String)

        public var errorDescription: String? {
            switch self {
            case .pathNotFound(let path):
                "Path does not exist: \(path)"
            case .directoryUnreadable(let path):
                "Cannot enumerate directory: \(path)"
            }
        }
    }

    /// Directory names to exclude from scanning.
    private static let excludedDirectories: Set<String> = [
        ".build",
        "checkouts",
        ".index-build"
    ]

    public init() {}

    /// Collects all `.swift` files under the given path.
    ///
    /// If `path` points to a single file, returns that file (if it has a `.swift` extension).
    /// If `path` points to a directory, recursively walks it, skipping excluded directories.
    ///
    /// - Parameter path: A file or directory path to scan.
    /// - Returns: An array of absolute paths to `.swift` files.
    /// - Throws: `FileScanner.Error` if the path does not exist or the directory cannot be enumerated.
    public func collectSwiftFiles(at path: String) throws(Error) -> [String] {
        let url = URL(fileURLWithPath: path).standardized
        var isDirectory: ObjCBool = false

        guard FileManager.default.fileExists(atPath: url.path, isDirectory: &isDirectory) else {
            throw .pathNotFound(path)
        }

        if !isDirectory.boolValue {
            return url.pathExtension == "swift" ? [url.path] : []
        }

        return try collectFromDirectory(url)
    }
}

private extension FileScanner {
    func collectFromDirectory(_ directory: URL) throws(Error) -> [String] {
        let fileManager = FileManager.default
        var results: [String] = []

        guard let enumerator = fileManager.enumerator(
            at: directory,
            includingPropertiesForKeys: [.isDirectoryKey],
            options: [.skipsHiddenFiles]
        ) else {
            throw .directoryUnreadable(directory.path)
        }

        for case let fileURL as URL in enumerator {
            let fileName = fileURL.lastPathComponent

            // Skip excluded directories
            if Self.excludedDirectories.contains(fileName) {
                enumerator.skipDescendants()
                continue
            }

            // Also skip hidden directories (starting with .) that aren't caught by skipsHiddenFiles
            // because skipsHiddenFiles may not cover all cases
            if fileName.hasPrefix(".") {
                let resourceValues = try? fileURL.resourceValues(forKeys: [.isDirectoryKey])
                if resourceValues?.isDirectory == true {
                    enumerator.skipDescendants()
                    continue
                }
            }

            // Collect .swift files
            if fileURL.pathExtension == "swift" {
                results.append(fileURL.path)
            }
        }

        return results.sorted()
    }
}
