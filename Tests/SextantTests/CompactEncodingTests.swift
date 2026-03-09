//
//  CompactEncodingTests.swift
//  Sextant
//
//  Created by Mathew Gacy on 3/8/26.
//  Copyright © 2026 Mathew Gacy. All rights reserved.
//

@testable import SextantLib
import Foundation
import Testing

@Suite("Compact JSON Encoding")
struct CompactEncodingTests {

    @Test("Declaration JSON omits empty arrays and empty strings")
    func declarationOmitsEmptyFields() throws {
        let decl = Declaration(
            name: "fetchUser",
            kind: .function,
            line: 42,
            fullDeclaration: "func fetchUser()"
        )

        let encoder = JSONEncoder()
        let data = try encoder.encode(decl)
        let json = String(data: data, encoding: .utf8)!

        // Should NOT contain empty optional fields
        #expect(!json.contains("\"attributes\""))
        #expect(!json.contains("\"conformances\""))
        #expect(!json.contains("\"children\""))
        #expect(!json.contains("\"associatedValues\""))

        // Should contain non-empty fields
        #expect(json.contains("\"fullDeclaration\""))
        #expect(json.contains("\"name\""))
        #expect(json.contains("\"kind\""))
        #expect(json.contains("\"line\""))
    }

    @Test("Declaration JSON includes non-empty optional fields")
    func declarationIncludesPopulatedFields() throws {
        let decl = Declaration(
            name: "State",
            kind: .struct,
            line: 10,
            attributes: ["@ObservableState"],
            conformances: ["Equatable"]
        )

        let encoder = JSONEncoder()
        let data = try encoder.encode(decl)
        let json = String(data: data, encoding: .utf8)!

        #expect(json.contains("\"attributes\""))
        #expect(json.contains("\"conformances\""))
        #expect(!json.contains("\"children\""))
        #expect(!json.contains("\"fullDeclaration\""))
    }

    @Test("Declaration decodes from compact JSON with missing keys")
    func declarationDecodesCompactJSON() throws {
        let json = """
        {"name":"test","kind":"function","line":1}
        """
        let data = Data(json.utf8)
        let decl = try JSONDecoder().decode(Declaration.self, from: data)

        #expect(decl.name == "test")
        #expect(decl.kind == .function)
        #expect(decl.line == 1)
        #expect(decl.attributes.isEmpty)
        #expect(decl.conformances.isEmpty)
        #expect(decl.children.isEmpty)
        #expect(decl.associatedValues.isEmpty)
        #expect(decl.fullDeclaration.isEmpty)
    }

    @Test("SymbolEntry JSON omits empty arrays")
    func symbolEntryOmitsEmptyFields() throws {
        let entry = SymbolEntry(
            name: "fetchUser",
            kind: .function,
            file: "test.swift",
            line: 42
        )

        let encoder = JSONEncoder()
        let data = try encoder.encode(entry)
        let json = String(data: data, encoding: .utf8)!

        #expect(!json.contains("\"attributes\""))
        #expect(!json.contains("\"conformances\""))
        #expect(!json.contains("\"associatedValues\""))
    }

    @Test("Declaration round-trips through JSON encode/decode")
    func declarationRoundTrips() throws {
        let original = Declaration(
            name: "Action",
            kind: .enum,
            line: 33,
            attributes: ["@CasePathable"],
            conformances: ["Equatable", "Sendable"],
            children: [
                Declaration(name: "onAppear", kind: .case, line: 34, fullDeclaration: "onAppear")
            ]
        )

        let data = try JSONEncoder().encode(original)
        let decoded = try JSONDecoder().decode(Declaration.self, from: data)

        #expect(original == decoded)
    }
}
