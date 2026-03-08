//
//  SymbolEntry.swift
//  Sextant
//
//  Created by Mathew Gacy on 3/8/26.
//  Copyright © 2026 Mathew Gacy. All rights reserved.
//

import Foundation

/// The kind of a Swift declaration.
public enum SymbolKind: String, Codable, Equatable, Sendable {
    case `struct`
    case `class`
    case `enum`
    case `protocol`
    case `typealias`
    case function
    case variable
    case `case`
    case initializer
    case `extension`
    case actor
    case macro
}

/// A single declaration extracted from a Swift source file.
///
/// This is an owned value type with no dependencies on SyntaxSparrow.
/// All information is captured at parse time.
/// Uses compact JSON encoding — empty arrays are omitted via `@OmitEmpty`.
public struct SymbolEntry: Codable, Equatable, Sendable {

    /// The declared name (e.g., "AppReducer", "onAppear", "fetched").
    public let name: String

    /// The kind of declaration.
    public let kind: SymbolKind

    /// The file path where this symbol is declared.
    public let file: String

    /// The 1-based line number of the declaration.
    public let line: Int

    /// Attributes applied to the declaration (e.g., "@Reducer", "@ObservableState").
    @OmitEmpty public var attributes: [String]

    /// Protocol conformances declared on this type (e.g., ["Equatable", "Sendable"]).
    @OmitEmpty public var conformances: [String]

    /// For enum cases: the full associated value declaration (e.g., "Result<Success, Failure>").
    /// Empty for non-case declarations.
    @OmitEmpty public var associatedValues: [String]

    /// Creates a symbol entry.
    ///
    /// - Parameters:
    ///   - name: The declared name.
    ///   - kind: The kind of declaration.
    ///   - file: The file path where this symbol is declared.
    ///   - line: The 1-based line number.
    ///   - attributes: Attributes applied to the declaration.
    ///   - conformances: Protocol conformances.
    ///   - associatedValues: Associated value types for enum cases.
    public init(
        name: String,
        kind: SymbolKind,
        file: String,
        line: Int,
        attributes: [String] = [],
        conformances: [String] = [],
        associatedValues: [String] = []
    ) {
        self.name = name
        self.kind = kind
        self.file = file
        self.line = line
        self.attributes = attributes
        self.conformances = conformances
        self.associatedValues = associatedValues
    }
}
