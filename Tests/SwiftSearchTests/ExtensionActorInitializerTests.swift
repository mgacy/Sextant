//
//  ExtensionActorInitializerTests.swift
//  Sextant
//
//  Created by Mathew Gacy on 3/8/26.
//  Copyright © 2026 Mathew Gacy. All rights reserved.
//

@testable import SwiftSearchLib
import Foundation
import Testing

@Suite("Extensions, Actors, Initializers")
struct ExtensionActorInitializerTests {
    let parser = FileParser()

    private func fixtureSource(_ name: String) -> String {
        let url = Bundle.module.url(forResource: name, withExtension: "swift", subdirectory: "Fixtures")!
        // swiftlint:disable:next force_try
        return try! String(contentsOf: url, encoding: .utf8)
    }

    @Test("Extracts extension with extended type as name and conformances")
    func extractsExtension() throws {
        let source = fixtureSource("DeclarationsFixture")
        let overview = parser.parseSource(source, file: "DeclarationsFixture.swift")

        let extensions = overview.declarations.filter { $0.kind == .extension }
        #expect(extensions.count == 2)

        let stringExt = try #require(extensions.first { $0.name == "String" })
        #expect(stringExt.conformances.contains("CustomPrintable"))
    }

    @Test("Extension children include member functions and variables")
    func extensionChildren() {
        let source = fixtureSource("DeclarationsFixture")
        let overview = parser.parseSource(source, file: "DeclarationsFixture.swift")

        let stringExt = overview.declarations.first { $0.kind == .extension && $0.name == "String" }!
        let functions = stringExt.children.filter { $0.kind == .function }
        let variables = stringExt.children.filter { $0.kind == .variable }

        #expect(functions.contains { $0.name == "trimmed" })
        #expect(variables.contains { $0.name == "isEmpty" })
    }

    @Test("Extracts actor with name, conformances, and children")
    func extractsActor() throws {
        let source = fixtureSource("DeclarationsFixture")
        let overview = parser.parseSource(source, file: "DeclarationsFixture.swift")

        let actor = try #require(overview.declarations.first { $0.kind == .actor })
        #expect(actor.name == "NetworkManager")
        #expect(actor.conformances.contains("Sendable"))

        let children = actor.children
        #expect(children.contains { $0.kind == .variable && $0.name == "requestCount" })
        #expect(children.contains { $0.kind == .function && $0.name == "fetch" })
    }

    @Test("Extracts initializers as children of containing struct")
    func extractsInitializers() {
        let source = fixtureSource("DeclarationsFixture")
        let overview = parser.parseSource(source, file: "DeclarationsFixture.swift")

        let settings = overview.declarations.first { $0.name == "Settings" }!
        let inits = settings.children.filter { $0.kind == .initializer }

        #expect(inits.count == 3)
        #expect(inits.allSatisfy { $0.name == "init" })
    }

    @Test("SimpleReducer extension is now visible as top-level declaration")
    func simpleReducerExtensionVisible() throws {
        let source = fixtureSource("SimpleReducer")
        let overview = parser.parseSource(source, file: "SimpleReducer.swift")

        let extensions = overview.declarations.filter { $0.kind == .extension }
        #expect(extensions.count == 1)
        #expect(extensions[0].name == "ItemListReducer")

        // The extension's core function should be a child
        let core = try #require(extensions[0].children.first { $0.name == "core" })
        #expect(core.kind == .function)
    }
}
