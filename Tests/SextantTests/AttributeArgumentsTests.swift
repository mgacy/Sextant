//
//  AttributeArgumentsTests.swift
//  Sextant
//
//  Created by Mathew Gacy on 9/22/26.
//  Copyright © 2026 Mathew Gacy. All rights reserved.
//

@testable import SextantLib
import Foundation
import Testing

@Suite("attributeArguments")
struct AttributeArgumentsTests {
    let overview: FileOverview

    init() throws {
        let url = try #require(Bundle.module.url(forResource: "AttributeArguments", withExtension: "swift", subdirectory: "Fixtures"))
        let source = try String(contentsOf: url, encoding: .utf8)
        overview = FileParser().parseSource(source, file: "AttributeArguments.swift")
    }

    private func member(_ name: String) throws -> Declaration {
        let fixture = try #require(overview.declarations.first { $0.name == "AttributeArgumentsFixture" })
        return try #require(fixture.children.first { $0.name == name })
    }

    // MARK: - Parsing

    @Test("A string-literal argument and a non-string trait are both retained as raw text")
    func stringAndTraitArguments() throws {
        let decl = try member("fetchesUser")

        #expect(decl.attributes == ["@Test"])
        #expect(decl.attributeArguments == [#""Fetches a user", .disabled("flaky on CI")"#])
        #expect(decl.arguments(ofAttribute: "@Test") == #""Fetches a user", .disabled("flaky on CI")"#)
    }

    @Test("Type-level attribute arguments are retained")
    func typeLevelArguments() throws {
        let fixture = try #require(overview.declarations.first { $0.name == "AttributeArgumentsFixture" })

        #expect(fixture.attributes == ["@Suite"])
        #expect(fixture.arguments(ofAttribute: "@Suite") == #""Attribute arguments", .serialized"#)
    }

    @Test("An attribute without parentheses leaves attributeArguments empty")
    func bareAttribute() throws {
        let decl = try member("bareTest")

        #expect(decl.attributes == ["@Test"])
        #expect(decl.attributeArguments.isEmpty)
        #expect(decl.arguments(ofAttribute: "@Test") == nil)
    }

    @Test("Empty parentheses are an empty argument list, not a missing one")
    func emptyParentheses() throws {
        let decl = try member("emptyParentheses")

        #expect(decl.attributeArguments == [""])
        #expect(decl.arguments(ofAttribute: "@Test") == "")
    }

    @Test("Arguments stay parallel to attributes, nil where an attribute has none")
    func mixedAttributes() throws {
        let decl = try member("mixed")

        #expect(decl.attributes == ["@MainActor", "@available"])
        #expect(decl.attributeArguments == [nil, "iOS 17, *"])
        #expect(decl.arguments(ofAttribute: "@MainActor") == nil)
        #expect(decl.arguments(ofAttribute: "@available") == "iOS 17, *")
    }

    @Test("A repeated attribute keeps each occurrence's arguments in order; lookup by name returns the first")
    func repeatedAttribute() throws {
        let decl = try member("repeated")

        #expect(decl.attributes == ["@available", "@available"])
        #expect(decl.attributeArguments == ["iOS, deprecated: 17", "macOS, deprecated: 14"])
        #expect(decl.arguments(ofAttribute: "@available") == "iOS, deprecated: 17")
    }

    @Test("A multi-line argument list with nested generics is retained verbatim, interior whitespace included")
    func multiLineArguments() throws {
        let decl = try member("multiLine")

        #expect(decl.arguments(ofAttribute: "@Test") == """
        "Multi-line display name",
                arguments: [Result<Int, any Error>.success(1)]
        """)
    }

    @Test("An #if clause in the attribute list is skipped by both attributes and arguments, keeping them aligned")
    func conditionalAttributeStaysAligned() throws {
        let decl = try member("conditional")

        #expect(decl.attributes == ["@available", "@objc"])
        #expect(decl.attributeArguments == ["iOS 16, *", "conditionalName"])
    }

    @Test("Enum case attribute arguments propagate to every element of the case declaration")
    func enumCaseArguments() throws {
        let event = try #require(overview.declarations.first { $0.name == "Event" })

        for name in ["legacy", "older"] {
            let element = try #require(event.children.first { $0.name == name })
            #expect(element.attributes == ["@available"])
            #expect(element.arguments(ofAttribute: "@available") == #"*, deprecated, message: "Use renamed""#)
        }
    }

    @Test("A name that is not among the attributes has no arguments")
    func unknownAttributeName() throws {
        #expect(try member("fetchesUser").arguments(ofAttribute: "@Suite") == nil)
    }

    // MARK: - Model

    @Test("An all-nil argument list is stored as empty")
    func allNilNormalizesToEmpty() {
        let decl = Declaration(
            name: "run",
            kind: .function,
            line: 1,
            attributes: ["@MainActor", "@discardableResult"],
            attributeArguments: [nil, nil]
        )

        #expect(decl.attributeArguments.isEmpty)
    }
}
