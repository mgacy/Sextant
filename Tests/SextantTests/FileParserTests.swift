//
//  FileParserTests.swift
//  Sextant
//
//  Created by Mathew Gacy on 3/8/26.
//  Copyright © 2026 Mathew Gacy. All rights reserved.
//

@testable import SextantLib
import Foundation
import Testing

@Suite("FileParser")
struct FileParserTests {
    let parser = FileParser()

    // MARK: - Fixture Loading

    private func fixtureURL(_ name: String) -> URL {
        Bundle.module.url(forResource: name, withExtension: "swift", subdirectory: "Fixtures")!
    }

    private func fixtureSource(_ name: String) -> String {
        // swiftlint:disable:next force_try
        try! String(contentsOf: fixtureURL(name), encoding: .utf8)
    }

    // MARK: - SimpleReducer Tests

    @Test("Extracts top-level declarations from SimpleReducer fixture")
    func extractsTopLevelDeclarations() {
        let source = fixtureSource("SimpleReducer")
        let overview = parser.parseSource(source, file: "SimpleReducer.swift")

        // Should find: 2 typealiases + 1 struct (ItemListReducer)
        let typealiases = overview.declarations.filter { $0.kind == .typealias }
        #expect(typealiases.count == 2)
        #expect(typealiases.contains { $0.name == "ItemListAction" })
        #expect(typealiases.contains { $0.name == "ItemListState" })

        let structs = overview.declarations.filter { $0.kind == .struct }
        #expect(structs.count == 1)
        #expect(structs[0].name == "ItemListReducer")
    }

    @Test("Extracts @Reducer attribute from ItemListReducer")
    func extractsReducerAttribute() throws {
        let source = fixtureSource("SimpleReducer")
        let overview = parser.parseSource(source, file: "SimpleReducer.swift")

        let reducer = try #require(overview.declarations.first { $0.name == "ItemListReducer" })
        #expect(reducer.attributes.contains("@Reducer"))
    }

    @Test("Extracts conformances from ItemListReducer")
    func extractsConformances() throws {
        let source = fixtureSource("SimpleReducer")
        let overview = parser.parseSource(source, file: "SimpleReducer.swift")

        let reducer = try #require(overview.declarations.first { $0.name == "ItemListReducer" })
        #expect(reducer.conformances.contains("Reducer"))
        #expect(reducer.conformances.contains("Sendable"))
    }

    @Test("Extracts nested State struct with @ObservableState attribute")
    func extractsNestedState() throws {
        let source = fixtureSource("SimpleReducer")
        let overview = parser.parseSource(source, file: "SimpleReducer.swift")

        let reducer = try #require(overview.declarations.first { $0.name == "ItemListReducer" })
        let state = try #require(reducer.children.first { $0.name == "State" })
        #expect(state.kind == .struct)
        #expect(state.attributes.contains("@ObservableState"))
        #expect(state.conformances.contains("Equatable"))
    }

    @Test("Extracts nested Destination enum with @Reducer attribute")
    func extractsNestedDestination() throws {
        let source = fixtureSource("SimpleReducer")
        let overview = parser.parseSource(source, file: "SimpleReducer.swift")

        let reducer = try #require(overview.declarations.first { $0.name == "ItemListReducer" })
        let destination = try #require(reducer.children.first { $0.name == "Destination" })
        #expect(destination.kind == .enum)
        #expect(destination.attributes.contains("@Reducer"))
    }

    @Test("Extracts nested Action enum with cases")
    func extractsNestedAction() throws {
        let source = fixtureSource("SimpleReducer")
        let overview = parser.parseSource(source, file: "SimpleReducer.swift")

        let reducer = try #require(overview.declarations.first { $0.name == "ItemListReducer" })
        let action = try #require(reducer.children.first { $0.name == "Action" })
        #expect(action.kind == .enum)
        #expect(action.conformances.contains("BindableAction"))
        #expect(action.conformances.contains("Equatable"))
        #expect(action.conformances.contains("Sendable"))

        // Check that it has cases as children
        let cases = action.children.filter { $0.kind == .case }
        #expect(cases.count >= 4)
        #expect(cases.contains { $0.name == "onAppear" })
        #expect(cases.contains { $0.name == "itemsFetched" })
    }

    @Test("Extracts @Dependency variables inside ItemListReducer")
    func extractsDependencyVariables() throws {
        let source = fixtureSource("SimpleReducer")
        let overview = parser.parseSource(source, file: "SimpleReducer.swift")

        let reducer = try #require(overview.declarations.first { $0.name == "ItemListReducer" })

        let variables = reducer.children.filter { $0.kind == .variable }
        let dependencyVars = variables.filter { $0.attributes.contains("@Dependency") }
        #expect(dependencyVars.count >= 2)
    }

    @Test("Extracts Action enum case with Result associated value")
    func extractsResultAssociatedValue() throws {
        let source = fixtureSource("SimpleReducer")
        let overview = parser.parseSource(source, file: "SimpleReducer.swift")

        let reducer = try #require(overview.declarations.first { $0.name == "ItemListReducer" })
        let action = try #require(reducer.children.first { $0.name == "Action" })
        let itemsFetched = try #require(action.children.first { $0.name == "itemsFetched" })
        #expect(itemsFetched.kind == .case)
        #expect(!itemsFetched.associatedValues.isEmpty)
        // The full declaration should contain the Result type
        #expect(itemsFetched.fullDeclaration.contains("Result"))
    }

    // MARK: - EnumWithAssociatedValues Tests

    @Test("Extracts enums with various associated value patterns")
    func extractsEnumsWithAssociatedValues() {
        let source = fixtureSource("EnumWithAssociatedValues")
        let overview = parser.parseSource(source, file: "EnumWithAssociatedValues.swift")

        let enums = overview.declarations.filter { $0.kind == .enum }
        #expect(enums.count == 3)
        #expect(enums.contains { $0.name == "NetworkResult" })
        #expect(enums.contains { $0.name == "DataEvent" })
        #expect(enums.contains { $0.name == "NavigationAction" })
    }

    @Test("Extracts enum case with Result generic associated value")
    func extractsResultGenericCase() throws {
        let source = fixtureSource("EnumWithAssociatedValues")
        let overview = parser.parseSource(source, file: "EnumWithAssociatedValues.swift")

        let dataEvent = try #require(overview.declarations.first { $0.name == "DataEvent" })
        let contentFetched = try #require(dataEvent.children.first { $0.name == "contentFetched" })
        #expect(contentFetched.fullDeclaration.contains("Result<PageContent, AppError>"))
    }

    @Test("Extracts enum case with labeled associated values")
    func extractsLabeledAssociatedValues() throws {
        let source = fixtureSource("EnumWithAssociatedValues")
        let overview = parser.parseSource(source, file: "EnumWithAssociatedValues.swift")

        let dataEvent = try #require(overview.declarations.first { $0.name == "DataEvent" })
        let settingsLoaded = try #require(dataEvent.children.first { $0.name == "settingsLoaded" })
        #expect(settingsLoaded.associatedValues.contains { $0.contains("config") })
        #expect(settingsLoaded.associatedValues.contains { $0.contains("isFirstLaunch") })
    }

    @Test("Extracts enum case with no payload")
    func extractsCaseWithNoPayload() throws {
        let source = fixtureSource("EnumWithAssociatedValues")
        let overview = parser.parseSource(source, file: "EnumWithAssociatedValues.swift")

        let dataEvent = try #require(overview.declarations.first { $0.name == "DataEvent" })
        let noPayload = try #require(dataEvent.children.first { $0.name == "noPayload" })
        #expect(noPayload.associatedValues.isEmpty)
        #expect(noPayload.fullDeclaration == "noPayload")
    }

    @Test("Extracts @CasePathable attribute from NavigationAction")
    func extractsCasePathable() throws {
        let source = fixtureSource("EnumWithAssociatedValues")
        let overview = parser.parseSource(source, file: "EnumWithAssociatedValues.swift")

        let nav = try #require(overview.declarations.first { $0.name == "NavigationAction" })
        #expect(nav.attributes.contains("@CasePathable"))
    }

    // MARK: - Typealias Tests

    @Test("Extracts typealias declarations")
    func extractsTypealiases() {
        let source = fixtureSource("Typealias")
        let overview = parser.parseSource(source, file: "Typealias.swift")

        let typealiases = overview.declarations.filter { $0.kind == .typealias }
        #expect(typealiases.count == 4)
        #expect(typealiases.contains { $0.name == "ItemListState" })
        #expect(typealiases.contains { $0.name == "ItemListAction" })
        #expect(typealiases.contains { $0.name == "AppState" })
        #expect(typealiases.contains { $0.name == "CompletionHandler" })
    }

    // MARK: - Class Tests

    @Test("Extracts class declarations with inheritance and children")
    func extractsClass() throws {
        let source = fixtureSource("DeclarationsFixture")
        let overview = parser.parseSource(source, file: "DeclarationsFixture.swift")

        let classDecl = try #require(overview.declarations.first { $0.kind == .class })
        #expect(classDecl.name == "DataManager")
        #expect(classDecl.conformances.contains("NSObject"))
        #expect(classDecl.conformances.contains("Sendable"))
        #expect(classDecl.children.contains { $0.kind == .variable && $0.name == "cache" })
        #expect(classDecl.children.contains { $0.kind == .function && $0.name == "clear" })
    }

    // MARK: - Protocol Tests

    @Test("Extracts protocol declarations with inheritance and member requirements")
    func extractsProtocol() throws {
        let source = fixtureSource("DeclarationsFixture")
        let overview = parser.parseSource(source, file: "DeclarationsFixture.swift")

        let protocolDecl = try #require(overview.declarations.first { $0.kind == .protocol })
        #expect(protocolDecl.name == "Repository")
        #expect(protocolDecl.conformances.contains("Sendable"))
        #expect(protocolDecl.children.contains { $0.kind == .function && $0.name == "fetchAll" })
        #expect(protocolDecl.children.contains { $0.kind == .function && $0.name == "save" })
    }

    // MARK: - Line Number Tests

    @Test("Line numbers are 1-based and monotonically increasing for top-level declarations")
    func lineNumbersAreCorrect() {
        let source = fixtureSource("SimpleReducer")
        let overview = parser.parseSource(source, file: "SimpleReducer.swift")

        // All declarations should have positive line numbers
        for decl in overview.declarations {
            #expect(decl.line > 0, "Declaration \(decl.name) has non-positive line number \(decl.line)")
        }

        // Top-level declarations should be in order
        for i in 1..<overview.declarations.count {
            #expect(
                overview.declarations[i].line >= overview.declarations[i - 1].line,
                "Declarations not in line order: \(overview.declarations[i - 1].name) at \(overview.declarations[i - 1].line) vs \(overview.declarations[i].name) at \(overview.declarations[i].line)"
            )
        }
    }

    // MARK: - Partial Parse Resilience

    @Test("Handles malformed Swift input without crashing")
    func partialParseResilience() {
        let malformedSource = """
        struct Incomplete {
            var x: Int
            // Missing closing brace

        enum Orphan {
            case valid
            case
        }

        func broken(param: -> Void {
        """

        let overview = parser.parseSource(malformedSource, file: "malformed.swift")

        // Should not crash, and should extract at least some declarations
        #expect(overview.file == "malformed.swift")
        // SwiftSyntax is resilient - it should find partial results
        #expect(overview.declarations.count >= 1, "Expected at least 1 declaration from malformed input, got \(overview.declarations.count)")
    }

    @Test("parseFile throws for nonexistent path")
    func parseFileThrowsForBadPath() {
        #expect(throws: FileParser.Error.self) {
            try parser.parseFile(at: "/nonexistent/path/file.swift")
        }
    }
}
