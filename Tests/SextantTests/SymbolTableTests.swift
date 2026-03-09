//
//  SymbolTableTests.swift
//  Sextant
//
//  Created by Mathew Gacy on 3/8/26.
//  Copyright © 2026 Mathew Gacy. All rights reserved.
//

@testable import SextantLib
import Foundation
import Testing

@Suite("SymbolTable")
struct SymbolTableTests {
    let parser = FileParser()

    private func fixtureSource(_ name: String) -> String {
        let url = Bundle.module.url(forResource: name, withExtension: "swift", subdirectory: "Fixtures")!
        // swiftlint:disable:next force_try
        return try! String(contentsOf: url, encoding: .utf8)
    }

    @Test("Looks up symbol by exact name")
    func lookupByName() {
        let source = fixtureSource("SimpleReducer")
        let overview = parser.parseSource(source, file: "SimpleReducer.swift")

        let table = SymbolTable(overviews: [overview])

        let results = table.lookup(name: "ItemListReducer")
        #expect(results.count == 2) // struct + extension
        #expect(results.contains { $0.kind == .struct && $0.attributes.contains("@Reducer") })
        #expect(results.contains { $0.kind == .extension })
    }

    @Test("Looks up symbol by name and kind")
    func lookupByNameAndKind() {
        let source = fixtureSource("SimpleReducer")
        let overview = parser.parseSource(source, file: "SimpleReducer.swift")

        let table = SymbolTable(overviews: [overview])

        // ItemListState appears as both a typealias (top-level) and a nested struct State
        let typealiases = table.lookup(name: "ItemListState", kind: .typealias)
        #expect(typealiases.count == 1)
        #expect(typealiases[0].kind == .typealias)
    }

    @Test("Looks up nested symbol by name with parent context")
    func lookupNestedSymbol() {
        let source = fixtureSource("SimpleReducer")
        let overview = parser.parseSource(source, file: "SimpleReducer.swift")

        let table = SymbolTable(overviews: [overview])

        let results = table.lookup(name: "State")
        #expect(results.count >= 1)
        #expect(results.contains { $0.kind == .struct })
        #expect(results.contains { $0.parentName == "ItemListReducer" })
    }

    @Test("Returns empty array for missing symbol")
    func lookupMissingSymbol() {
        let source = fixtureSource("SimpleReducer")
        let overview = parser.parseSource(source, file: "SimpleReducer.swift")

        let table = SymbolTable(overviews: [overview])

        let results = table.lookup(name: "NonExistentSymbol")
        #expect(results.isEmpty)
    }

    @Test("Indexes symbols from multiple file overviews")
    func indexesMultipleFiles() {
        let source1 = fixtureSource("SimpleReducer")
        let source2 = fixtureSource("EnumWithAssociatedValues")
        let overview1 = parser.parseSource(source1, file: "SimpleReducer.swift")
        let overview2 = parser.parseSource(source2, file: "EnumWithAssociatedValues.swift")

        let table = SymbolTable(overviews: [overview1, overview2])

        // ItemListReducer from file 1 (struct + extension)
        let itemListReducer = table.lookup(name: "ItemListReducer")
        #expect(itemListReducer.count == 2)
        #expect(itemListReducer.allSatisfy { $0.file == "SimpleReducer.swift" })

        // NetworkResult from file 2
        let networkResult = table.lookup(name: "NetworkResult")
        #expect(networkResult.count == 1)
        #expect(networkResult[0].file == "EnumWithAssociatedValues.swift")
    }

    @Test("Lookup includes file and line information")
    func lookupIncludesFileAndLine() {
        let source = fixtureSource("SimpleReducer")
        let overview = parser.parseSource(source, file: "SimpleReducer.swift")

        let table = SymbolTable(overviews: [overview])

        let results = table.lookup(name: "ItemListReducer", kind: .struct)
        #expect(results.count == 1)
        #expect(results[0].file == "SimpleReducer.swift")
        #expect(results[0].line > 0)
    }

    @Test("Extension members are findable via lookup")
    func lookupExtensionMembers() {
        let source = fixtureSource("DeclarationsFixture")
        let overview = parser.parseSource(source, file: "DeclarationsFixture.swift")

        let table = SymbolTable(overviews: [overview])

        let results = table.lookup(name: "trimmed")
        #expect(results.count == 1)
        #expect(results[0].kind == .function)
        #expect(results[0].fullDeclaration.contains("trimmed"))
    }

    @Test("Top-level symbols have empty parentName")
    func topLevelParentName() {
        let source = fixtureSource("SimpleReducer")
        let overview = parser.parseSource(source, file: "SimpleReducer.swift")

        let table = SymbolTable(overviews: [overview])

        let results = table.lookup(name: "ItemListReducer", kind: .struct)
        #expect(results.count == 1)
        #expect(results[0].parentName.isEmpty)
    }

    @Test("Nested symbols include parent name")
    func nestedSymbolParentName() {
        let source = fixtureSource("SimpleReducer")
        let overview = parser.parseSource(source, file: "SimpleReducer.swift")

        let table = SymbolTable(overviews: [overview])

        // Action is nested inside ItemListReducer
        let actions = table.lookup(name: "Action", kind: .enum)
        #expect(actions.contains { $0.parentName == "ItemListReducer" })

        // Delegate is nested inside Action (fully-qualified)
        let delegates = table.lookup(name: "Delegate", kind: .enum)
        #expect(delegates.contains { $0.parentName == "ItemListReducer.Action" })
    }

    @Test("Lookup includes full declaration for functions")
    func lookupIncludesFullDeclaration() {
        let source = fixtureSource("DeclarationsFixture")
        let overview = parser.parseSource(source, file: "DeclarationsFixture.swift")

        let table = SymbolTable(overviews: [overview])

        let results = table.lookup(name: "fetchUser", kind: .function)
        #expect(results.count == 1)
        #expect(results[0].fullDeclaration.contains("fetchUser"))
        #expect(results[0].fullDeclaration.contains("UUID"))
    }
}
