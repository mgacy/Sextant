//
//  FileParser+References.swift
//  Sextant
//
//  Created by Mathew Gacy on 3/15/26.
//

import Foundation
import SwiftParser
import SwiftSyntax

public extension FileParser {

    /// Finds all type-position references to `name` in a Swift source string.
    ///
    /// Searches declaration-level type positions (inheritance clauses, parameter types, return types,
    /// type annotations, typealias targets, and generic constraints). Does not match inside function
    /// bodies, variable initializers, computed property bodies, or import statements.
    ///
    /// - Parameters:
    ///   - name: The type name to search for (exact match against identifier tokens).
    ///   - source: The Swift source code string.
    ///   - file: The file path to associate with matches (for display purposes).
    /// - Returns: An array of reference matches found in the source.
    func findReferences(to name: String, in source: String, file: String) -> [ReferenceMatch] {
        let sourceFile = Parser.parse(source: source)
        let converter = SourceLocationConverter(fileName: file, tree: sourceFile)
        let finder = TypeReferenceFinder(name: name, file: file, converter: converter)
        finder.walk(sourceFile)
        return finder.matches
    }

    /// Finds references in a single file at the given path.
    ///
    /// - Parameters:
    ///   - name: The type name to search for.
    ///   - path: Absolute path to a `.swift` file.
    /// - Returns: An array of reference matches found in the file.
    /// - Throws: `FileParser.Error.fileUnreadable` if the file cannot be read.
    func findReferences(to name: String, at path: String) throws(Error) -> [ReferenceMatch] {
        let source: String
        do {
            source = try String(contentsOf: URL(filePath: path), encoding: .utf8)
        } catch {
            throw .fileUnreadable(path: path, underlying: error)
        }
        return findReferences(to: name, in: source, file: path)
    }

    /// Finds references across multiple files concurrently.
    ///
    /// Files are searched in parallel using a `TaskGroup`. Results are sorted by file path
    /// for deterministic output. Parse failures for individual files are collected in the
    /// result rather than thrown.
    ///
    /// - Parameters:
    ///   - name: The type name to search for.
    ///   - paths: An array of absolute paths to `.swift` files.
    /// - Returns: A ``ReferenceResult`` containing matches and failures, sorted by file path.
    func findReferences(to name: String, atPaths paths: [String]) async -> ReferenceResult {
        let results = await withTaskGroup(
            of: (String, Swift.Result<[ReferenceMatch], FileParser.Error>).self
        ) { group in
            for file in paths {
                group.addTask {
                    do throws(FileParser.Error) {
                        let matches = try self.findReferences(to: name, at: file)
                        return (file, .success(matches))
                    } catch {
                        return (file, .failure(error))
                    }
                }
            }

            var collected: [(String, Swift.Result<[ReferenceMatch], FileParser.Error>)] = []
            collected.reserveCapacity(paths.count)
            for await result in group {
                collected.append(result)
            }
            return collected
        }

        let sorted = results.sorted { $0.0 < $1.0 }

        var allMatches: [ReferenceMatch] = []
        var failures: [ParseFailure] = []
        var scannedFileCount = 0

        for (file, result) in sorted {
            switch result {
            case .success(let matches):
                allMatches.append(contentsOf: matches)
                scannedFileCount += 1
            case .failure(let error):
                failures.append(ParseFailure(file: file, error: error))
            }
        }

        return ReferenceResult(
            matches: allMatches,
            failures: failures,
            scannedFileCount: scannedFileCount
        )
    }

    /// Scans a path for Swift files and finds references concurrently.
    ///
    /// If `path` points to a single file, searches just that file. If `path` points to a directory,
    /// recursively scans for `.swift` files (excluding build artifacts) and searches all of them.
    ///
    /// - Parameters:
    ///   - name: The type name to search for.
    ///   - path: A file or directory path to scan.
    /// - Returns: A ``ReferenceResult`` containing matches and failures.
    /// - Throws: `FileScanner.Error` if the path does not exist or the directory cannot be enumerated.
    func findReferences(to name: String, in path: String) async throws(FileScanner.Error) -> ReferenceResult {
        let scanner = FileScanner()
        let files = try scanner.collectSwiftFiles(at: path)
        return await findReferences(to: name, atPaths: files)
    }
}
