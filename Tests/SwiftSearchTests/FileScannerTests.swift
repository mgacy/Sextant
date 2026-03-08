//
//  FileScannerTests.swift
//  Sextant
//
//  Created by Mathew Gacy on 3/8/26.
//  Copyright © 2026 Mathew Gacy. All rights reserved.
//

@testable import SwiftSearchLib
import Foundation
import Testing

@Suite("FileScanner")
struct FileScannerTests {
    let scanner = FileScanner()

    // MARK: - Helpers

    /// Creates a temporary directory with a unique name for test isolation.
    private func makeTempDir() throws -> URL {
        let dir = FileManager.default.temporaryDirectory
            .appendingPathComponent("FileScannerTests-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir
    }

    /// Creates an empty file at the given path.
    private func createFile(at url: URL) throws {
        try FileManager.default.createDirectory(
            at: url.deletingLastPathComponent(),
            withIntermediateDirectories: true
        )
        try Data().write(to: url)
    }

    // MARK: - Single File Tests

    @Test("Single .swift file returns its path")
    func singleSwiftFile() throws {
        let dir = try makeTempDir()
        defer { try? FileManager.default.removeItem(at: dir) }

        let file = dir.appendingPathComponent("Hello.swift")
        try createFile(at: file)

        let results = try scanner.collectSwiftFiles(at: file.path)
        #expect(results == [file.path])
    }

    @Test("Single non-Swift file throws notSwiftFile")
    func singleNonSwiftFile() throws {
        let dir = try makeTempDir()
        defer { try? FileManager.default.removeItem(at: dir) }

        let file = dir.appendingPathComponent("readme.txt")
        try createFile(at: file)

        #expect(throws: FileScanner.Error.self) {
            try scanner.collectSwiftFiles(at: file.path)
        }
    }

    @Test("Nonexistent path throws pathNotFound")
    func nonexistentPath() {
        #expect(throws: FileScanner.Error.self) {
            try scanner.collectSwiftFiles(at: "/nonexistent/path/to/nothing")
        }
    }

    // MARK: - Directory Tests

    @Test("Directory with mixed files returns only .swift files, sorted")
    func mixedDirectory() throws {
        let dir = try makeTempDir()
        defer { try? FileManager.default.removeItem(at: dir) }

        let swift1 = dir.appendingPathComponent("Beta.swift")
        let swift2 = dir.appendingPathComponent("Alpha.swift")
        let txt = dir.appendingPathComponent("notes.txt")
        let json = dir.appendingPathComponent("config.json")

        try createFile(at: swift1)
        try createFile(at: swift2)
        try createFile(at: txt)
        try createFile(at: json)

        let results = try scanner.collectSwiftFiles(at: dir.path)
        #expect(results.count == 2)
        // Results should be sorted
        #expect(results[0].hasSuffix("Alpha.swift"))
        #expect(results[1].hasSuffix("Beta.swift"))
    }

    @Test("Excluded directories (.build, checkouts, .index-build) are skipped")
    func excludedDirectories() throws {
        let dir = try makeTempDir()
        defer { try? FileManager.default.removeItem(at: dir) }

        // Good file at root
        try createFile(at: dir.appendingPathComponent("Root.swift"))

        // Files inside excluded directories
        try createFile(at: dir.appendingPathComponent(".build/Package.swift"))
        try createFile(at: dir.appendingPathComponent("checkouts/Dep.swift"))
        try createFile(at: dir.appendingPathComponent(".index-build/Index.swift"))

        let results = try scanner.collectSwiftFiles(at: dir.path)
        #expect(results.count == 1)
        #expect(results[0].hasSuffix("Root.swift"))
    }

    @Test("Hidden directories are skipped")
    func hiddenDirectories() throws {
        let dir = try makeTempDir()
        defer { try? FileManager.default.removeItem(at: dir) }

        try createFile(at: dir.appendingPathComponent("Visible.swift"))
        try createFile(at: dir.appendingPathComponent(".hidden/Secret.swift"))

        let results = try scanner.collectSwiftFiles(at: dir.path)
        #expect(results.count == 1)
        #expect(results[0].hasSuffix("Visible.swift"))
    }

    @Test("Nested .swift files are found recursively")
    func nestedSwiftFiles() throws {
        let dir = try makeTempDir()
        defer { try? FileManager.default.removeItem(at: dir) }

        try createFile(at: dir.appendingPathComponent("Root.swift"))
        try createFile(at: dir.appendingPathComponent("Sources/Lib/File.swift"))
        try createFile(at: dir.appendingPathComponent("Sources/Lib/Sub/Deep.swift"))

        let results = try scanner.collectSwiftFiles(at: dir.path)
        #expect(results.count == 3)
        // All should be .swift files
        #expect(results.allSatisfy { $0.hasSuffix(".swift") })
    }

    @Test("Empty directory returns empty array")
    func emptyDirectory() throws {
        let dir = try makeTempDir()
        defer { try? FileManager.default.removeItem(at: dir) }

        let results = try scanner.collectSwiftFiles(at: dir.path)
        #expect(results.isEmpty)
    }
}
