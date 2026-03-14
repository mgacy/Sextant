//
//  ConcurrencyTests.swift
//  SextantTests
//
//  Created by Mathew Gacy on 3/13/26.
//  Copyright © 2026 Mathew Gacy. All rights reserved.
//

@testable import SextantLib
import Foundation
import Testing

@Suite("Concurrency")
struct ConcurrencyTests {
    let parser = FileParser()

    /// Fixture names available in the test bundle.
    private static let fixtureNames = [
        "DeclarationsFixture",
        "EnumWithAssociatedValues",
        "SimpleReducer",
        "Typealias"
    ]

    // MARK: - Fixture Loading

    private func fixturePath(_ name: String) -> String {
        Bundle.module.url(forResource: name, withExtension: "swift", subdirectory: "Fixtures")!.path
    }

    private var fixturesDirectory: String {
        Bundle.module.url(forResource: "DeclarationsFixture", withExtension: "swift", subdirectory: "Fixtures")!
            .deletingLastPathComponent().path
    }

    // MARK: - Deterministic Ordering

    @Test("Concurrent parsing produces deterministic file-path-sorted order across multiple runs")
    func deterministicOrdering() async {
        let fixturePaths = Self.fixtureNames.map { fixturePath($0) }

        // Run the concurrent parse multiple times to verify ordering stability.
        var previousOrder: [String]?

        for iteration in 0..<10 {
            let result = await parser.parseFiles(atPaths: fixturePaths)

            // All results should be successes.
            #expect(result.failures.isEmpty, "Unexpected failures in iteration \(iteration)")

            let filePaths = result.overviews.map(\.file)

            // Verify ordering is identical to the previous iteration.
            if let previous = previousOrder {
                #expect(
                    filePaths == previous,
                    "Ordering changed between iterations \(iteration - 1) and \(iteration)"
                )
            }
            previousOrder = filePaths
        }

        // Verify the sorted order is lexicographic.
        if let order = previousOrder {
            let lexicographic = order.sorted()
            #expect(order == lexicographic, "Final order should be lexicographically sorted by file path")
        }
    }

    // MARK: - Error Tolerance

    @Test("Concurrent parsing with invalid paths collects errors without discarding valid results")
    func errorTolerance() async {
        let validPaths = Self.fixtureNames.map { fixturePath($0) }
        let invalidPaths = [
            "/nonexistent/path/Missing1.swift",
            "/nonexistent/path/Missing2.swift"
        ]
        let allPaths = validPaths + invalidPaths

        let result = await parser.parseFiles(atPaths: allPaths)

        // All valid fixture files should parse successfully.
        #expect(
            result.overviews.count == validPaths.count,
            "Expected \(validPaths.count) successes, got \(result.overviews.count)"
        )

        // All invalid paths should produce failures.
        #expect(
            result.failures.count == invalidPaths.count,
            "Expected \(invalidPaths.count) failures, got \(result.failures.count)"
        )

        // Verify failures are for the invalid paths specifically.
        let failedPaths = Set(result.failures.map(\.file))
        for invalidPath in invalidPaths {
            #expect(failedPaths.contains(invalidPath), "Expected failure for \(invalidPath)")
        }

        // Verify valid results contain expected declarations — not empty overviews.
        for overview in result.overviews {
            #expect(!overview.declarations.isEmpty, "Expected non-empty declarations for \(overview.file)")
        }
    }

    // MARK: - ParseResult Properties

    @Test("ParseResult.totalCount returns sum of successes and failures")
    func totalCount() async {
        let validPaths = Self.fixtureNames.map { fixturePath($0) }
        let invalidPaths = ["/nonexistent/Missing.swift"]
        let allPaths = validPaths + invalidPaths

        let result = await parser.parseFiles(atPaths: allPaths)

        #expect(result.totalCount == allPaths.count)
    }

    @Test("ParseResult.allFailed is true only when all files fail")
    func allFailed() async {
        // All valid — should not be allFailed.
        let validPaths = Self.fixtureNames.map { fixturePath($0) }
        let validResult = await parser.parseFiles(atPaths: validPaths)
        #expect(!validResult.allFailed)

        // All invalid — should be allFailed.
        let invalidPaths = ["/nonexistent/A.swift", "/nonexistent/B.swift"]
        let failedResult = await parser.parseFiles(atPaths: invalidPaths)
        #expect(failedResult.allFailed)

        // Empty — should not be allFailed.
        let emptyResult = await parser.parseFiles(atPaths: [])
        #expect(!emptyResult.allFailed)
    }

    // MARK: - parseFiles(in:)

    @Test("parseFiles(in:) with nonexistent path throws FileScanner.Error.pathNotFound")
    func parseFilesInNonexistentPath() async throws {
        await #expect(throws: FileScanner.Error.self) {
            try await parser.parseFiles(in: "/nonexistent/directory")
        }
    }

    @Test("parseFiles(in:) with non-Swift file throws FileScanner.Error.notSwiftFile")
    func parseFilesInNonSwiftFile() async throws {
        // Create a temporary non-Swift file.
        let tempDir = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        let tempFile = tempDir.appendingPathComponent("data.json")
        try FileManager.default.createDirectory(at: tempDir, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: tempDir) }
        try "{}".write(to: tempFile, atomically: true, encoding: .utf8)

        await #expect(throws: FileScanner.Error.self) {
            try await parser.parseFiles(in: tempFile.path)
        }
    }

    @Test("parseFiles(in:) with valid directory returns parsed results")
    func parseFilesInDirectory() async throws {
        let result = try await parser.parseFiles(in: fixturesDirectory)

        #expect(!result.overviews.isEmpty, "Expected parsed overviews from fixtures directory")
        #expect(result.failures.isEmpty, "Expected no failures from valid fixtures")
        #expect(result.overviews.count >= Self.fixtureNames.count)
    }

    @Test("parseFiles(in:) with single Swift file returns one overview")
    func parseFilesInSingleFile() async throws {
        let singleFile = fixturePath("SimpleReducer")
        let result = try await parser.parseFiles(in: singleFile)

        #expect(result.overviews.count == 1)
        #expect(result.failures.isEmpty)
        #expect(!result.overviews[0].declarations.isEmpty)
    }
}
