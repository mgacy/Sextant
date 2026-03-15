//
//  TypeReferences.swift
//  Sextant
//

import Foundation

// MARK: - Inheritance

protocol TargetProtocol {}

struct ConformingStruct: TargetType {
    var value: Int
}

// MARK: - Enum with associated value

enum Action {
    case fetched(TargetType)
    case other(String)
}

// MARK: - Function parameter and return type

func process(input: TargetType) -> TargetType {
    // TargetType() -- should NOT match (function body)
    fatalError()
}

// MARK: - Variable type annotation

var globalTarget: TargetType = {
    // TargetType inside initializer should NOT match
    fatalError()
}()

// MARK: - Typealias

typealias Alias = TargetType

// MARK: - Generic constraint

func constrained<T>(value: T) -> T where T: TargetType {
    fatalError()
}

// MARK: - Nested types and parent chain

struct Outer {
    struct Inner {
        var nested: TargetType
    }
}

// MARK: - Extension with inheritance

extension String: TargetType {}

// MARK: - Computed property body exclusion

struct ComputedExample {
    var computed: Int {
        let x: TargetType? = nil
        return 0
    }
}

// MARK: - Variable initializer exclusion

struct InitializerExample {
    var defaulted: String = TargetType.description
}

// MARK: - MemberTypeSyntax

struct MemberTypeExample {
    var state: Foo.Bar
}

// MARK: - Closure type in annotation

struct ClosureExample {
    var handler: (TargetType) -> Void
}

// MARK: - Import exclusion (cannot actually use `import struct` for TargetType,
// but the visitor should skip ImportDeclSyntax regardless)

// MARK: - Protocol associatedtype constraint

protocol Container {
    associatedtype Element: TargetType
}
