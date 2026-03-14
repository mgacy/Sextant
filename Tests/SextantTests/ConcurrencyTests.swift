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

    // MARK: - Deterministic Ordering

    @Test("Concurrent parsing produces deterministic file-path-sorted order across multiple runs")
    func deterministicOrdering() async {
        let fixturePaths = Self.fixtureNames.map { fixturePath($0) }

        // Run the concurrent parse pattern multiple times to verify ordering stability.
        var previousOrder: [String]?

        for iteration in 0..<10 {
            let overviews = await withTaskGroup(
                of: (String, Result<FileOverview, any Error>).self
            ) { group in
                for path in fixturePaths {
                    group.addTask {
                        do {
                            return (path, .success(try parser.parseFile(at: path)))
                        } catch {
                            return (path, .failure(error))
                        }
                    }
                }

                var collected: [(String, Result<FileOverview, any Error>)] = []
                collected.reserveCapacity(fixturePaths.count)
                for await result in group {
                    collected.append(result)
                }
                return collected
            }

            // Sort by file path — same as scanAndParse does.
            let sorted = overviews.sorted { $0.0 < $1.0 }
            let filePaths = sorted.map(\.0)

            // All results should be successes.
            for (path, result) in sorted {
                switch result {
                case .success:
                    break
                case .failure(let error):
                    Issue.record("Unexpected failure for \(path): \(error)")
                }
            }

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
        // swiftlint:disable:previous function_body_length
        let validPaths = Self.fixtureNames.map { fixturePath($0) }
        let invalidPaths = [
            "/nonexistent/path/Missing1.swift",
            "/nonexistent/path/Missing2.swift"
        ]
        let allPaths = validPaths + invalidPaths

        let results = await withTaskGroup(
            of: (String, Result<FileOverview, any Error>).self
        ) { group in
            for path in allPaths {
                group.addTask {
                    do {
                        return (path, .success(try parser.parseFile(at: path)))
                    } catch {
                        return (path, .failure(error))
                    }
                }
            }

            var collected: [(String, Result<FileOverview, any Error>)] = []
            collected.reserveCapacity(allPaths.count)
            for await result in group {
                collected.append(result)
            }
            return collected
        }

        // Sort by file path for deterministic processing.
        let sorted = results.sorted { $0.0 < $1.0 }

        var successes: [FileOverview] = []
        var failures: [(path: String, error: any Error)] = []

        for (path, result) in sorted {
            switch result {
            case .success(let overview):
                successes.append(overview)
            case .failure(let error):
                failures.append((path: path, error: error))
            }
        }

        // All valid fixture files should parse successfully.
        #expect(
            successes.count == validPaths.count,
            "Expected \(validPaths.count) successes, got \(successes.count)"
        )

        // All invalid paths should produce failures.
        #expect(
            failures.count == invalidPaths.count,
            "Expected \(invalidPaths.count) failures, got \(failures.count)"
        )

        // Verify failures are for the invalid paths specifically.
        let failedPaths = Set(failures.map(\.path))
        for invalidPath in invalidPaths {
            #expect(
                failedPaths.contains(invalidPath),
                "Expected failure for \(invalidPath)"
            )
        }

        // Verify failures are FileParser.Error instances.
        for failure in failures {
            #expect(
                failure.error is FileParser.Error,
                "Expected FileParser.Error for \(failure.path), got \(type(of: failure.error))"
            )
        }

        // Verify valid results contain expected declarations — not empty overviews.
        for overview in successes {
            #expect(
                !overview.declarations.isEmpty,
                "Expected non-empty declarations for \(overview.file)"
            )
        }
    }
}
