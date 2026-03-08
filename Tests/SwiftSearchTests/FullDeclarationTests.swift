//
//  FullDeclarationTests.swift
//  Sextant
//
//  Created by Mathew Gacy on 3/8/26.
//  Copyright © 2026 Mathew Gacy. All rights reserved.
//

@testable import SwiftSearchLib
import Foundation
import Testing

@Suite("fullDeclaration")
struct FullDeclarationTests {
    let parser = FileParser()

    private func fixtureSource(_ name: String) -> String {
        let url = Bundle.module.url(forResource: name, withExtension: "swift", subdirectory: "Fixtures")!
        // swiftlint:disable:next force_try
        return try! String(contentsOf: url, encoding: .utf8)
    }

    // MARK: - Functions

    @Test("Simple function fullDeclaration")
    func simpleFunctionDeclaration() {
        let source = fixtureSource("DeclarationsFixture")
        let overview = parser.parseSource(source, file: "test.swift")

        let simple = overview.declarations.first { $0.name == "simple" }
        #expect(simple != nil)
        #expect(simple!.fullDeclaration == "func simple()")
    }

    @Test("Static function with params and return type")
    func staticFunctionDeclaration() {
        let source = fixtureSource("DeclarationsFixture")
        let overview = parser.parseSource(source, file: "test.swift")

        let validate = overview.declarations.first { $0.name == "validate" }
        #expect(validate != nil)
        #expect(validate!.fullDeclaration == "static func validate(_ input: String) -> Bool")
    }

    @Test("Async throws function with default param")
    func asyncThrowsFunctionDeclaration() {
        let source = fixtureSource("DeclarationsFixture")
        let overview = parser.parseSource(source, file: "test.swift")

        let fetchUser = overview.declarations.first { $0.name == "fetchUser" }
        #expect(fetchUser != nil)
        #expect(fetchUser!.fullDeclaration.contains("async"))
        #expect(fetchUser!.fullDeclaration.contains("throws"))
        #expect(fetchUser!.fullDeclaration.contains("-> User"))
        #expect(fetchUser!.fullDeclaration.contains("includeProfile: Bool = true"))
    }

    @Test("Mutating function")
    func mutatingFunctionDeclaration() {
        let source = fixtureSource("DeclarationsFixture")
        let overview = parser.parseSource(source, file: "test.swift")

        let reset = overview.declarations.first { $0.name == "reset" }
        #expect(reset != nil)
        #expect(reset!.fullDeclaration == "mutating func reset()")
    }

    // MARK: - Variables

    @Test("Var with type annotation")
    func varDeclaration() {
        let source = fixtureSource("DeclarationsFixture")
        let overview = parser.parseSource(source, file: "test.swift")

        let isLoading = overview.declarations.first { $0.name == "isLoading" }
        #expect(isLoading != nil)
        #expect(isLoading!.fullDeclaration == "var isLoading: Bool")
    }

    @Test("Let with type annotation")
    func letDeclaration() {
        let source = fixtureSource("DeclarationsFixture")
        let overview = parser.parseSource(source, file: "test.swift")

        let name = overview.declarations.first { $0.kind == .variable && $0.name == "name" }
        #expect(name != nil)
        #expect(name!.fullDeclaration == "let name: String")
    }

    @Test("Static var")
    func staticVarDeclaration() {
        let source = fixtureSource("DeclarationsFixture")
        let overview = parser.parseSource(source, file: "test.swift")

        let shared = overview.declarations.first { $0.name == "shared" }
        #expect(shared != nil)
        #expect(shared!.fullDeclaration == "static var shared: NetworkManager")
    }

    @Test("Variable with modifier detail (private(set))")
    func privateSetVarDeclaration() {
        let source = fixtureSource("DeclarationsFixture")
        let overview = parser.parseSource(source, file: "test.swift")

        let count = overview.declarations.first { $0.name == "count" }
        #expect(count != nil)
        #expect(count!.fullDeclaration.contains("private(set)"))
        #expect(count!.fullDeclaration.contains("var count: Int"))
    }

    // MARK: - Initializers

    @Test("Regular initializer fullDeclaration")
    func regularInitDeclaration() {
        let source = fixtureSource("DeclarationsFixture")
        let overview = parser.parseSource(source, file: "test.swift")

        let settings = overview.declarations.first { $0.name == "Settings" }!
        let inits = settings.children.filter { $0.kind == .initializer }

        let regularInit = inits.first { $0.fullDeclaration.contains("id: UUID") }
        #expect(regularInit != nil)
        #expect(regularInit!.fullDeclaration == "init(id: UUID, name: String)")
    }

    @Test("Failable initializer fullDeclaration")
    func failableInitDeclaration() {
        let source = fixtureSource("DeclarationsFixture")
        let overview = parser.parseSource(source, file: "test.swift")

        let settings = overview.declarations.first { $0.name == "Settings" }!
        let inits = settings.children.filter { $0.kind == .initializer }

        let failableInit = inits.first { $0.fullDeclaration.contains("init?") }
        #expect(failableInit != nil)
        #expect(failableInit!.fullDeclaration == "init?(rawValue: String)")
    }

    @Test("Throwing initializer fullDeclaration")
    func throwingInitDeclaration() {
        let source = fixtureSource("DeclarationsFixture")
        let overview = parser.parseSource(source, file: "test.swift")

        let settings = overview.declarations.first { $0.name == "Settings" }!
        let inits = settings.children.filter { $0.kind == .initializer }

        let throwingInit = inits.first { $0.fullDeclaration.contains("throws") }
        #expect(throwingInit != nil)
        #expect(throwingInit!.fullDeclaration == "public init() throws")
    }

    // MARK: - SimpleReducer Regression

    @Test("SimpleReducer body variable gets fullDeclaration with some keyword")
    func simpleReducerBodyDeclaration() {
        let source = fixtureSource("SimpleReducer")
        let overview = parser.parseSource(source, file: "SimpleReducer.swift")

        let reducer = overview.declarations.first { $0.name == "ItemListReducer" && $0.kind == .struct }!
        let body = reducer.children.first { $0.name == "body" }

        #expect(body != nil)
        #expect(body!.fullDeclaration.contains("var body"))
        #expect(body!.fullDeclaration.contains("ReducerOf"))
    }

    @Test("SimpleReducer init gets fullDeclaration")
    func simpleReducerInitDeclaration() {
        let source = fixtureSource("SimpleReducer")
        let overview = parser.parseSource(source, file: "SimpleReducer.swift")

        let reducer = overview.declarations.first { $0.name == "ItemListReducer" && $0.kind == .struct }!
        let initDecl = reducer.children.first { $0.kind == .initializer }

        #expect(initDecl != nil)
        #expect(initDecl!.fullDeclaration == "public init()")
    }
}
