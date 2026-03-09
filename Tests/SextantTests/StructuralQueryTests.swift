//
//  StructuralQueryTests.swift
//  Sextant
//
//  Created by Mathew Gacy on 3/8/26.
//  Copyright © 2026 Mathew Gacy. All rights reserved.
//

@testable import SextantLib
import Foundation
import Testing

@Suite("StructuralQuery")
struct StructuralQueryTests {
    let parser = FileParser()
    let query = StructuralQuery()

    private func fixtureSource(_ name: String) -> String {
        let url = Bundle.module.url(forResource: name, withExtension: "swift", subdirectory: "Fixtures")!
        // swiftlint:disable:next force_try
        return try! String(contentsOf: url, encoding: .utf8)
    }

    @Test("Finds enum cases matching pattern by case name substring")
    func findsCasesByNameSubstring() throws {
        let source = fixtureSource("EnumWithAssociatedValues")
        let overview = parser.parseSource(source, file: "EnumWithAssociatedValues.swift")

        let matches = try query.findEnumCases(matching: "Fetched", in: [overview])

        // Should match contentFetched and profileUpdated (which doesn't contain "Fetched")
        #expect(matches.contains { $0.caseName == "contentFetched" })
        #expect(!matches.contains { $0.caseName == "profileUpdated" })
    }

    @Test("Finds enum cases matching pattern by associated value type")
    func findsCasesByAssociatedValueType() throws {
        let source = fixtureSource("EnumWithAssociatedValues")
        let overview = parser.parseSource(source, file: "EnumWithAssociatedValues.swift")

        let matches = try query.findEnumCases(matching: "Result<", in: [overview])

        // Should match contentFetched, profileUpdated, and batchCompleted
        #expect(matches.count >= 2)
        #expect(matches.contains { $0.caseName == "contentFetched" })
        #expect(matches.contains { $0.caseName == "profileUpdated" })
    }

    @Test("Finds enum cases across multiple file overviews")
    func findsCasesAcrossFiles() throws {
        let source1 = fixtureSource("SimpleReducer")
        let source2 = fixtureSource("EnumWithAssociatedValues")
        let overview1 = parser.parseSource(source1, file: "SimpleReducer.swift")
        let overview2 = parser.parseSource(source2, file: "EnumWithAssociatedValues.swift")

        // "Result" should match cases in both files
        let matches = try query.findEnumCases(matching: "Result", in: [overview1, overview2])
        #expect(matches.count >= 2)
    }

    @Test("Returns empty array for pattern with no matches")
    func returnsEmptyForNoMatches() throws {
        let source = fixtureSource("EnumWithAssociatedValues")
        let overview = parser.parseSource(source, file: "EnumWithAssociatedValues.swift")

        let matches = try query.findEnumCases(matching: "zzzzNonExistent", in: [overview])
        #expect(matches.isEmpty)
    }

    @Test("Throws error for invalid regex pattern")
    func throwsForInvalidRegex() {
        let source = fixtureSource("EnumWithAssociatedValues")
        let overview = parser.parseSource(source, file: "EnumWithAssociatedValues.swift")

        #expect(throws: StructuralQuery.Error.self) {
            try query.findEnumCases(matching: "[invalid", in: [overview])
        }
    }

    @Test("Filters symbols by kind")
    func filtersSymbolsByKind() {
        let source = fixtureSource("EnumWithAssociatedValues")
        let overview = parser.parseSource(source, file: "EnumWithAssociatedValues.swift")

        let enums = query.findSymbols(ofKind: .enum, in: [overview])
        #expect(enums.count == 3)
        #expect(enums.allSatisfy { $0.kind == .enum })
    }
}
