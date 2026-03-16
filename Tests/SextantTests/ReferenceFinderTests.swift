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
        #expect(inheritance.count == 1)
        #expect(inheritance.first?.name == "TargetType")
    }

    @Test("Finds reference in enum associated value")
    func findsAssociatedValueReference() {
        let matches = findTargetTypeReferences()
        let assocValue = matches.filter { $0.position == .associatedValue && $0.declarationName == "fetched" }
        #expect(assocValue.count == 1)
        #expect(assocValue.first?.name == "TargetType")
    }

    @Test("Finds reference in function parameter type")
    func findsParameterTypeReference() {
        let matches = findTargetTypeReferences()
        let paramType = matches.filter { $0.position == .parameterType && $0.declarationName == "process" }
        #expect(paramType.count == 1)
        #expect(paramType.first?.name == "TargetType")
    }

    @Test("Finds reference in return type")
    func findsReturnTypeReference() {
        let matches = findTargetTypeReferences()
        let returnType = matches.filter { $0.position == .returnType && $0.declarationName == "process" }
        #expect(returnType.count == 1)
        #expect(returnType.first?.name == "TargetType")
    }

    @Test("Finds reference in variable type annotation")
    func findsTypeAnnotationReference() {
        let matches = findTargetTypeReferences()
        let typeAnnotation = matches.filter { $0.position == .typeAnnotation && $0.declarationName == "globalTarget" }
        #expect(typeAnnotation.count == 1)
        #expect(typeAnnotation.first?.name == "TargetType")
    }

    @Test("Finds reference in typealias target")
    func findsTypealiasTargetReference() {
        let matches = findTargetTypeReferences()
        let typealiasTarget = matches.filter { $0.position == .typealiasTarget && $0.declarationName == "Alias" }
        #expect(typealiasTarget.count == 1)
        #expect(typealiasTarget.first?.name == "TargetType")
    }

    @Test("Finds reference in generic where clause")
    func findsGenericConstraintReference() {
        let matches = findTargetTypeReferences()
        let generic = matches.filter { $0.position == .genericConstraint && $0.declarationName == "constrained" }
        #expect(generic.count == 1)
        #expect(generic.first?.name == "TargetType")
    }

    @Test("Finds reference in inline generic parameter constraint")
    func findsInlineGenericConstraintReference() {
        let matches = findTargetTypeReferences()
        let inline = matches.filter { $0.position == .genericConstraint && $0.declarationName == "inlineConstrained" }
        #expect(inline.count == 1)
        #expect(inline.first?.name == "TargetType")
    }

    @Test("Finds reference in extension inheritance clause")
    func findsExtensionInheritanceReference() {
        let matches = findTargetTypeReferences()
        let extInheritance = matches.filter { $0.position == .inheritance && $0.declarationKind == .extension }
        #expect(extInheritance.count == 1)
        #expect(extInheritance.first?.name == "TargetType")
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

    @Test("Does NOT match inside import statement")
    func excludesImportStatement() {
        let source = """
        import struct Foundation.TargetType
        struct S: TargetType {}
        """
        let matches = parser.findReferences(to: "TargetType", in: source, file: "test.swift")
        #expect(matches.count == 1)
        #expect(matches.first?.position == .inheritance)
    }

    @Test("Tracks parent chain for nested declarations")
    func tracksParentChain() {
        let matches = findTargetTypeReferences()
        let nested = matches.filter { $0.declarationName == "nested" }
        #expect(nested.count == 1)
        #expect(nested.first?.parentName.contains("Outer") == true)
        #expect(nested.first?.parentName.contains("Inner") == true)
    }

    @Test("MemberTypeSyntax: searching base name matches full member type")
    func matchesMemberTypeByBaseName() {
        let source = fixtureSource("TypeReferences")
        let matches = parser.findReferences(to: "Foo", in: source, file: "TypeReferences.swift")
        let memberMatch = matches.filter { $0.name == "Foo.Bar" }
        #expect(memberMatch.count == 1)
    }

    @Test("MemberTypeSyntax: searching qualified name matches full member type")
    func matchesMemberTypeByQualifiedName() {
        let source = fixtureSource("TypeReferences")
        let matches = parser.findReferences(to: "Foo.Bar", in: source, file: "TypeReferences.swift")
        #expect(matches.count == 1)
        #expect(matches.first?.name == "Foo.Bar")
        #expect(matches.first?.position == .typeAnnotation)
    }

    @Test("MemberTypeSyntax: searching member name matches full member type")
    func matchesMemberTypeByMemberName() {
        let source = fixtureSource("TypeReferences")
        let matches = parser.findReferences(to: "Bar", in: source, file: "TypeReferences.swift")
        let memberMatch = matches.filter { $0.name == "Foo.Bar" }
        #expect(memberMatch.count == 1)
        #expect(memberMatch.first?.position == .typeAnnotation)
    }

    @Test("MemberTypeSyntax: finds type in generic argument")
    func findsMemberTypeGenericArgument() {
        let source = fixtureSource("TypeReferences")
        let matches = parser.findReferences(to: "Baz", in: source, file: "TypeReferences.swift")
        #expect(matches.count == 1)
        #expect(matches.first?.name == "Baz")
        #expect(matches.first?.position == .typeAnnotation)
    }

    @Test("Closure type in annotation classified as typeAnnotation")
    func classifiesClosureTypeAsAnnotation() {
        let matches = findTargetTypeReferences()
        let closureRef = matches.filter { $0.declarationName == "handler" && $0.position == .typeAnnotation }
        #expect(closureRef.count == 1)
        #expect(closureRef.first?.name == "TargetType")
    }

    @Test("Protocol associatedtype constraint classified as inheritance")
    func classifiesAssociatedTypeConstraint() {
        let matches = findTargetTypeReferences()
        let assocType = matches.filter { $0.declarationName == "Container" && $0.position == .inheritance }
        #expect(assocType.count == 1)
        #expect(assocType.first?.name == "TargetType")
    }

    @Test("Returns empty array when no matches exist")
    func returnsEmptyForNoMatches() {
        let source = fixtureSource("TypeReferences")
        let matches = parser.findReferences(to: "NonExistentType", in: source, file: "test.swift")
        #expect(matches.isEmpty)
    }
}
