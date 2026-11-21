//
//  FileOverview.swift
//  Sextant
//
//  Created by Mathew Gacy on 3/8/26.
//  Copyright © 2026 Mathew Gacy. All rights reserved.
//

import Foundation

/// A declaration within a file, potentially containing nested children.
///
/// This is an owned value type with no dependencies on swift-syntax.
/// Uses compact JSON encoding — empty arrays and empty strings are omitted via `@OmitEmpty`.
public struct Declaration: Codable, Equatable, Sendable {

    /// The declared name.
    public let name: String

    /// The kind of declaration.
    public let kind: SymbolKind

    /// The 1-based line number of the declaration.
    public let line: Int

    /// Attributes applied to the declaration (e.g., "@Reducer", "@ObservableState").
    @OmitEmpty public var attributes: [String]

    /// The raw argument text of each entry in ``attributes``, in the same order — the source between
    /// the attribute's parentheses (e.g., `"Fetches a user", .disabled("flaky")` for
    /// `@Test("Fetches a user", .disabled("flaky"))`), or `nil` for an attribute written without them.
    ///
    /// Empty when no attribute has arguments. Use ``arguments(ofAttribute:)`` to read by name.
    @OmitEmpty public var attributeArguments: [String?]

    /// Protocol conformances declared on this type.
    @OmitEmpty public var conformances: [String]

    /// Nested declarations (e.g., State and Action inside a reducer struct).
    @OmitEmpty public var children: [Declaration]

    /// For enum cases: the associated value labels and types (e.g., ["Result<Success, Failure>"]).
    /// Empty for non-case declarations.
    @OmitEmpty public var associatedValues: [String]

    /// The full serialized declaration (e.g., "func fetchUser(id: UUID) async throws -> User").
    /// Used for pattern matching in structural queries. Empty string when not applicable.
    @OmitEmpty public var fullDeclaration: String

    /// Creates a declaration.
    ///
    /// - Parameters:
    ///   - name: The declared name.
    ///   - kind: The kind of declaration.
    ///   - line: The 1-based line number.
    ///   - attributes: Attributes applied to the declaration.
    ///   - attributeArguments: The raw argument text of each attribute, `nil` where it has none. Stored
    ///     as empty when every entry is `nil`.
    ///   - conformances: Protocol conformances.
    ///   - children: Nested child declarations.
    ///   - associatedValues: Associated value types for enum cases.
    ///   - fullDeclaration: Full serialized declaration for pattern matching.
    public init(
        name: String,
        kind: SymbolKind,
        line: Int,
        attributes: [String] = [],
        attributeArguments: [String?] = [],
        conformances: [String] = [],
        children: [Declaration] = [],
        associatedValues: [String] = [],
        fullDeclaration: String = ""
    ) {
        self.name = name
        self.kind = kind
        self.line = line
        self.attributes = attributes
        self.attributeArguments = attributeArguments.allSatisfy { $0 == nil } ? [] : attributeArguments
        self.conformances = conformances
        self.children = children
        self.associatedValues = associatedValues
        self.fullDeclaration = fullDeclaration
    }
}

// MARK: - Attribute Arguments

public extension Declaration {
    /// Returns the raw argument text of the first attribute named `name`.
    ///
    /// - Parameter name: The attribute as it appears in ``attributes``, including the `@` (e.g., `"@Test"`).
    /// - Returns: The text between the attribute's parentheses, or `nil` if no attribute has that name or
    ///   it was written without parentheses.
    func arguments(ofAttribute name: String) -> String? {
        guard let index = attributes.firstIndex(of: name), attributeArguments.indices.contains(index) else {
            return nil
        }
        return attributeArguments[index]
    }
}

/// An overview of all top-level declarations in a Swift source file.
///
/// This is an owned value type with no dependencies on swift-syntax.
public struct FileOverview: Codable, Equatable, Sendable {

    /// The path to the source file.
    public let file: String

    /// Top-level declarations in the file.
    public let declarations: [Declaration]

    /// Creates a file overview.
    ///
    /// - Parameters:
    ///   - file: The path to the source file.
    ///   - declarations: Top-level declarations in the file.
    public init(file: String, declarations: [Declaration]) {
        self.file = file
        self.declarations = declarations
    }
}
