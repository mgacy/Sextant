//
//  ReferenceFinderTests.swift
//  Sextant
//
//  Created by Mathew Gacy on 3/15/26.
//

@testable import SextantLib
import Foundation
import Testing

@Suite("ReferenceFinder")
struct ReferenceFinderTests {
    let parser = FileParser()

    private func fixtureSource(_ name: String) -> String {
        let url = Bundle.module.url(forResource: name, withExtension: "swift", subdirectory: "Fixtures")!
        // swiftlint:disable:next force_try
        return try! String(contentsOf: url, encoding: .utf8)
    }

    private func findTargetTypeReferences() -> [ReferenceMatch] {
        let source = fixtureSource("TypeReferences")
        return parser.findReferences(to: "TargetType", in: source, file: "TypeReferences.swift")
    }

    @Test("Finds reference in inheritance clause")
    func findsInheritanceReference() {
        let matches = findTargetTypeReferences()
        let inheritance = matches.filter { $0.position == .inheritance && $0.declarationName == "ConformingStruct" }
        #expect(!inheritance.isEmpty)
    }

    @Test("Finds reference in enum associated value")
    func findsAssociatedValueReference() {
        let matches = findTargetTypeReferences()
        let assocValue = matches.filter { $0.position == .associatedValue && $0.declarationName == "fetched" }
        #expect(!assocValue.isEmpty)
    }

    @Test("Finds reference in function parameter type")
    func findsParameterTypeReference() {
        let matches = findTargetTypeReferences()
        let paramType = matches.filter { $0.position == .parameterType && $0.declarationName == "process" }
        #expect(!paramType.isEmpty)
    }

    @Test("Finds reference in return type")
    func findsReturnTypeReference() {
        let matches = findTargetTypeReferences()
        let returnType = matches.filter { $0.position == .returnType && $0.declarationName == "process" }
        #expect(!returnType.isEmpty)
    }

    @Test("Finds reference in variable type annotation")
    func findsTypeAnnotationReference() {
        let matches = findTargetTypeReferences()
        let typeAnnotation = matches.filter { $0.position == .typeAnnotation && $0.declarationName == "globalTarget" }
        #expect(!typeAnnotation.isEmpty)
    }

    @Test("Finds reference in typealias target")
    func findsTypealiasTargetReference() {
        let matches = findTargetTypeReferences()
        let typealiasTarget = matches.filter { $0.position == .typealiasTarget && $0.declarationName == "Alias" }
        #expect(!typealiasTarget.isEmpty)
    }

    @Test("Finds reference in generic where clause")
    func findsGenericConstraintReference() {
        let matches = findTargetTypeReferences()
        let generic = matches.filter { $0.position == .genericConstraint && $0.declarationName == "constrained" }
        #expect(!generic.isEmpty)
    }

    @Test("Finds reference in extension inheritance clause")
    func findsExtensionInheritanceReference() {
        let matches = findTargetTypeReferences()
        let extInheritance = matches.filter { $0.position == .inheritance && $0.declarationKind == .extension }
        #expect(!extInheritance.isEmpty)
    }

    @Test("Does NOT match inside function body")
    func excludesFunctionBody() {
        let source = """
        func example() -> Int {
            let x: TargetType = TargetType()
            return 0
        }
        """
        let matches = parser.findReferences(to: "TargetType", in: source, file: "test.swift")
        #expect(matches.isEmpty)
    }

    @Test("Does NOT match inside variable initializer")
    func excludesVariableInitializer() {
        let source = """
        var x: String = TargetType.description
        """
        let matches = parser.findReferences(to: "TargetType", in: source, file: "test.swift")
        // Should only find the String reference if searching for "String", not TargetType in initializer
        #expect(matches.isEmpty)
    }

    @Test("Does NOT match inside computed property body")
    func excludesComputedPropertyBody() {
        let source = """
        struct Example {
            var computed: Int {
                let x: TargetType? = nil
                return 0
            }
        }
        """
        let matches = parser.findReferences(to: "TargetType", in: source, file: "test.swift")
        #expect(matches.isEmpty)
    }

    @Test("Tracks parent chain for nested declarations")
    func tracksParentChain() {
        let matches = findTargetTypeReferences()
        let nested = matches.filter { $0.declarationName == "nested" }
        #expect(nested.first?.parentName.contains("Outer") == true)
        #expect(nested.first?.parentName.contains("Inner") == true)
    }

    @Test("MemberTypeSyntax: searching base name matches full member type")
    func matchesMemberTypeByBaseName() {
        let source = fixtureSource("TypeReferences")
        let matches = parser.findReferences(to: "Foo", in: source, file: "TypeReferences.swift")
        let memberMatch = matches.filter { $0.name == "Foo.Bar" }
        #expect(!memberMatch.isEmpty)
    }

    @Test("Closure type in annotation classified as typeAnnotation")
    func classifiesClosureTypeAsAnnotation() {
        let matches = findTargetTypeReferences()
        let closureRef = matches.filter { $0.declarationName == "handler" && $0.position == .typeAnnotation }
        #expect(!closureRef.isEmpty)
    }

    @Test("Protocol associatedtype constraint classified as inheritance")
    func classifiesAssociatedTypeConstraint() {
        let matches = findTargetTypeReferences()
        // No AssociatedTypeDeclSyntax context push -- declarationName is the enclosing protocol
        let assocType = matches.filter { $0.declarationName == "Element" || $0.declarationName == "Container" }
        let inheritance = assocType.filter { $0.position == .inheritance }
        #expect(!inheritance.isEmpty)
    }

    @Test("Returns empty array when no matches exist")
    func returnsEmptyForNoMatches() {
        let source = fixtureSource("TypeReferences")
        let matches = parser.findReferences(to: "NonExistentType", in: source, file: "test.swift")
        #expect(matches.isEmpty)
    }
}
