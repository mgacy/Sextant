//
//  FullDeclarationTests.swift
//  Sextant
//
//  Created by Mathew Gacy on 3/8/26.
//  Copyright © 2026 Mathew Gacy. All rights reserved.
//

@testable import SextantLib
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
    func simpleFunctionDeclaration() throws {
        let source = fixtureSource("DeclarationsFixture")
        let overview = parser.parseSource(source, file: "test.swift")

        let simple = try #require(overview.declarations.first { $0.name == "simple" })
        #expect(simple.fullDeclaration == "func simple()")
    }

    @Test("Static function with params and return type")
    func staticFunctionDeclaration() throws {
        let source = fixtureSource("DeclarationsFixture")
        let overview = parser.parseSource(source, file: "test.swift")

        let validate = try #require(overview.declarations.first { $0.name == "validate" })
        #expect(validate.fullDeclaration == "static func validate(_ input: String) -> Bool")
    }

    @Test("Async throws function with default param")
    func asyncThrowsFunctionDeclaration() throws {
        let source = fixtureSource("DeclarationsFixture")
        let overview = parser.parseSource(source, file: "test.swift")

        let fetchUser = try #require(overview.declarations.first { $0.name == "fetchUser" })
        #expect(fetchUser.fullDeclaration.contains("async"))
        #expect(fetchUser.fullDeclaration.contains("throws"))
        #expect(fetchUser.fullDeclaration.contains("-> User"))
        #expect(fetchUser.fullDeclaration.contains("includeProfile: Bool = true"))
    }

    @Test("Mutating function")
    func mutatingFunctionDeclaration() throws {
        let source = fixtureSource("DeclarationsFixture")
        let overview = parser.parseSource(source, file: "test.swift")

        let reset = try #require(overview.declarations.first { $0.name == "reset" })
        #expect(reset.fullDeclaration == "mutating func reset()")
    }

    // MARK: - Variables

    @Test("Var with type annotation")
    func varDeclaration() throws {
        let source = fixtureSource("DeclarationsFixture")
        let overview = parser.parseSource(source, file: "test.swift")

        let isLoading = try #require(overview.declarations.first { $0.name == "isLoading" })
        #expect(isLoading.fullDeclaration == "var isLoading: Bool")
    }

    @Test("Let with type annotation")
    func letDeclaration() throws {
        let source = fixtureSource("DeclarationsFixture")
        let overview = parser.parseSource(source, file: "test.swift")

        let name = try #require(overview.declarations.first { $0.kind == .variable && $0.name == "name" })
        #expect(name.fullDeclaration == "let name: String")
    }

    @Test("Static var")
    func staticVarDeclaration() throws {
        let source = fixtureSource("DeclarationsFixture")
        let overview = parser.parseSource(source, file: "test.swift")

        let shared = try #require(overview.declarations.first { $0.name == "shared" })
        #expect(shared.fullDeclaration == "static var shared: NetworkManager")
    }

    @Test("Variable with modifier detail (private(set))")
    func privateSetVarDeclaration() throws {
        let source = fixtureSource("DeclarationsFixture")
        let overview = parser.parseSource(source, file: "test.swift")

        let count = try #require(overview.declarations.first { $0.name == "count" })
        #expect(count.fullDeclaration.contains("private(set)"))
        #expect(count.fullDeclaration.contains("var count: Int"))
    }

    // MARK: - Initializers

    @Test("Regular initializer fullDeclaration")
    func regularInitDeclaration() throws {
        let source = fixtureSource("DeclarationsFixture")
        let overview = parser.parseSource(source, file: "test.swift")

        let settings = try #require(overview.declarations.first { $0.name == "Settings" })
        let inits = settings.children.filter { $0.kind == .initializer }

        let regularInit = try #require(inits.first { $0.fullDeclaration.contains("id: UUID") })
        #expect(regularInit.fullDeclaration == "init(id: UUID, name: String)")
    }

    @Test("Failable initializer fullDeclaration")
    func failableInitDeclaration() throws {
        let source = fixtureSource("DeclarationsFixture")
        let overview = parser.parseSource(source, file: "test.swift")

        let settings = try #require(overview.declarations.first { $0.name == "Settings" })
        let inits = settings.children.filter { $0.kind == .initializer }

        let failableInit = try #require(inits.first { $0.fullDeclaration.contains("init?") })
        #expect(failableInit.fullDeclaration == "init?(rawValue: String)")
    }

    @Test("Throwing initializer fullDeclaration")
    func throwingInitDeclaration() throws {
        let source = fixtureSource("DeclarationsFixture")
        let overview = parser.parseSource(source, file: "test.swift")

        let settings = try #require(overview.declarations.first { $0.name == "Settings" })
        let inits = settings.children.filter { $0.kind == .initializer }

        let throwingInit = try #require(inits.first { $0.fullDeclaration.contains("throws") })
        #expect(throwingInit.fullDeclaration == "public init() throws")
    }

    // MARK: - SimpleReducer Regression

    @Test("SimpleReducer body variable gets fullDeclaration with some keyword")
    func simpleReducerBodyDeclaration() throws {
        let source = fixtureSource("SimpleReducer")
        let overview = parser.parseSource(source, file: "SimpleReducer.swift")

        let reducer = try #require(overview.declarations.first { $0.name == "ItemListReducer" && $0.kind == .struct })
        let body = try #require(reducer.children.first { $0.name == "body" })
        #expect(body.fullDeclaration.contains("var body"))
        #expect(body.fullDeclaration.contains("ReducerOf"))
    }

    @Test("SimpleReducer init gets fullDeclaration")
    func simpleReducerInitDeclaration() throws {
        let source = fixtureSource("SimpleReducer")
        let overview = parser.parseSource(source, file: "SimpleReducer.swift")

        let reducer = try #require(overview.declarations.first { $0.name == "ItemListReducer" && $0.kind == .struct })
        let initDecl = try #require(reducer.children.first { $0.kind == .initializer })
        #expect(initDecl.fullDeclaration == "public init()")
    }
}
